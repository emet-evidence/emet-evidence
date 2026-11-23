#!/usr/bin/env python3
"""P0 visualisations (EMET v0.8) computed from the structured review data/reviews/<topic>.json.

No model call: everything is derived from the locked data. Components:
- prisma(review): PRISMA 2020 flow diagram by unit (records, reports, studies), two branches;
- grade_summary(review, page): GRADE by outcome, visible, with sample sizes and reasons for downgrading;
- study_explorer(review, page): filterable table of studies (type, outcome, risk of bias, access);
- rob_matrix(review, page): risk of bias by study and by domain, per tool, filterable by outcome;
- downloads(subject): open data files (written by export_package);
- export_package(subject): writes <open_data_dir>/<topic>/ (emet.json, default open-data) (CSV, JSON, SHA-256 manifest, zip archive).

User-facing text is localised with emet.i18n (English message ids, catalogs in emet/locales/).
"""
import csv, hashlib, io, json, math, zipfile
from collections import Counter, OrderedDict
from html import escape
from pathlib import Path

from emet.i18n import N_, _, _p, fmt_number
from emet.workspace import DEFAULT_ARMS, ROOT, METHODOLOGY, config, output_path

# Display labels are English message ids, translated with _() where they are rendered.
LEVEL = {'low': (N_('Low'), '+'), 'some': (N_('Some concerns'), '!'), 'high': (N_('High'), '−'), 'critical': (N_('Critical'), '×'), 'unclear': (N_('Unclear'), '?')}
KIND = {'primary': N_('Primary study'), 'systematic_review': N_('Systematic review'), 'registry': N_('Registry record'), 'unknown': N_('Not specified')}
ACCESS = {'full_text': N_('Full text'), 'abstract': N_('Abstract only'), 'registry': N_('Registry'), 'title_only': N_('Title only'), 'unknown': N_('Not specified')}
GRADE_DOMAINS = [('risk_of_bias', N_('Risk of bias')), ('inconsistency', N_('Inconsistency')), ('indirectness', N_('Indirectness')),
                 ('imprecision', N_('Imprecision')), ('publication_bias', N_('Publication bias'))]
# Descriptions of the rigour profiles (`description` of methodology/profiles/*.json, written in English), shown in the
# reproducibility block and translated with _(); keep in sync with the profiles.
PROFILE_DESCRIPTIONS = {
    'rapid': N_('Rapid profile (v0.6 budget). Does not claim compliance with a full systematic review: partial dual extraction.'),
    'standard': N_('Exhaustive dual independent screening and dual extraction. Does not by itself confer Cochrane compliance (subscription databases not searched).'),
    'exploratory': N_('Exploration: must not be presented as a systematic review. Single reviewer at each stage, scripted checks kept.'),
    'enhanced': N_('Exhaustive dual independent screening and dual extraction with different model families when available, adversarial search for missed studies, independent red team on the conclusion.'),
    'maximum': N_('Multiple independent search strategies, full audit of exclusions, multiple checks and cross-model adjudication.'),
}


def fmt(n):
    return fmt_number(n) if isinstance(n, int) else '—'


def judgement_level(text):
    # Matches the judgement text as written in the review data (French), not display text.
    t = (text or '').lower()
    for prefix, level in (('faible', 'low'), ('oui', 'low'), ('préoccupation', 'some'), ('partiel', 'some'), ('élevé', 'high'),
                          ('non rapporté', 'unclear'), ('non', 'high'), ('critique', 'critical'), ('incertain', 'unclear')):
        if t.startswith(prefix):
            return level
    return 'unclear'


OVERALL = {  # written overall judgement (review data) → level, by tool (first matching pattern)
    'RoB 2': [('faible', 'low'), ('préoccupation', 'some'), ('élevé', 'high')],
    'ROBINS-I': [('critique', 'critical'), ('sérieux', 'high'), ('modéré', 'some'), ('faible', 'low')],
    'AMSTAR 2': [('critiquement faible', 'critical'), ('modérée à faible', None), ('élevée', 'low'), ('modérée', 'some'), ('faible', 'high')],
}


def overall_level(item):
    """Displayed level: derived from the written overall judgement when unambiguous, otherwise the `level` field."""
    text = (item.get('overall') or '').lower()
    if text.startswith('non évaluable'):
        return 'unclear'
    for motif, level in OVERALL.get(item.get('tool'), []):
        if motif in text:
            return level or item.get('level', 'unclear')
    return item.get('level', 'unclear')


def resolved(review, stage):
    return {d['record']: d for d in review['screening_decisions'] if d['stage'] == stage and d['reviewer'] == 'resolved'}


def branches(review):
    other = {r['id'] for r in review['records'] if any(s.startswith('citations-') for s in r['sources'])}
    main = {r['id'] for r in review['records']} - other
    return main, other


def labelled(label, value):
    """`label: value` with the punctuation of the current language."""
    return _('{label}: {value}', label=label, value=value)


# ---- PRISMA 2020 by unit ----------------------------------------------------------------------------------

def prisma_counts(review):
    f = review['flow']
    main, other = branches(review)
    titles, abstracts, elig = resolved(review, 'titles'), resolved(review, 'abstracts'), resolved(review, 'eligibility')
    low = {d['record'] for d in review['screening_decisions'] if d['stage'] == 'prefilter-low-zone'}
    low_kept = {d['record'] for d in review['screening_decisions'] if d['stage'] == 'prefilter-low-zone' and d['decision'] == 'include'}
    prefiltered = {d['record'] for d in review['screening_decisions'] if d['stage'] == 'prefilter'}

    def branch(ids):
        t_ex = [i for i in ids if titles.get(i, {}).get('decision') == 'exclude']
        a = [i for i in ids if i in abstracts]
        a_ex = [i for i in a if abstracts[i]['decision'] == 'exclude']
        return {'records': len(ids), 'prefiltered': len(ids & prefiltered), 'low_read': len(ids & prefiltered & low),
                'low_kept': len(ids & low_kept), 'titles_excluded': len(t_ex), 'abstracts': len(a), 'abstracts_excluded': len(a_ex),
                'abstracts_codes': Counter(abstracts[i].get('code') or '—' for i in a_ex)}
    elig_codes = Counter(d.get('code') or '—' for d in elig.values() if d['decision'] == 'exclude')
    linked = sum(1 for s in review['studies'] if len(s['reports']) > 1)
    secondary = sum(len(s['reports']) - 1 for s in review['studies'])
    return {'f': f, 'main': branch(main), 'other': branch(other), 'elig_codes': elig_codes, 'linked': linked, 'secondary': secondary}


def prisma(review, codes, base):
    c = prisma_counts(review)
    f, m, o = c['f'], c['main'], c['other']

    def reasons(counter):
        # The exclusion code labels come from the review data; their short form is cut before " :" or " (".
        return '<ul class="p0-reasons">' + ''.join('<li>' + labelled(f'<abbr title="{escape(codes.get(code, ""))}">{escape(code)}</abbr> {escape(codes.get(code, "").split(" :")[0].split(" (")[0])}', fmt(n)) + '</li>'
                                                  for code, n in sorted(counter.items())) + '</ul>'

    def box(n, label, unit, note='', kind='', link=None):
        dl = f'<a class="p0-list" href="{base}/{link}" download>{_("list (CSV)")}</a>' if link else ''
        cls = {'': 'flow-box', ' side': 'flow-box notice', ' out': 'flow-box excluded', ' in': 'flow-box included'}[kind]
        return (f'<div class="{cls}" data-p0="{escape(label)}"><strong>{fmt(n)}</strong><span>{escape(label)}</span>'
                f'<em class="p0-unit">{unit}</em>{note}{dl}</div>')

    sources = ''.join(f'<li>{labelled(escape(k), fmt(v))}</li>' for k, v in f['identified_by_source'].items())
    row = lambda a, b='': f'<div class="p0-row">{a}{b or "<span></span>"}</div>'
    low_note = lambda b, extra: ('<small>' + _('including {n} in the low zone of the pre-filter, read once on title + abstract ({kept} kept{extra})',
                                               n=fmt(b["prefiltered"]), kept=fmt(b["low_kept"]), extra=extra) + '</small>')
    records, reports, studies = _('records'), _('reports'), _('studies')
    screened, title_ex, abstracts, abstract_ex = _('Records screened'), _('Excluded on title'), _('Abstracts assessed in duplicate'), _('Excluded on abstract')
    db = (row(box(f['identified_total'], _('Records identified'), records, f'<ul class="p0-reasons">{sources}</ul>'),
              box(f['duplicates_removed'], _('Duplicates removed'), records, kind=' out'))
          + row(box(m['records'], screened, records, link='prisma-notices.csv'),
                box(m['titles_excluded'], title_ex, records, low_note(m, _(': empty PubMed record, not assessable')), ' out', 'prisma-exclues-titres.csv'))
          + row(box(m['abstracts'], abstracts, records),
                box(m['abstracts_excluded'], abstract_ex, records, reasons(m['abstracts_codes']), ' out', 'prisma-exclues-resumes.csv')))
    other = (row(box(o['records'], _('Records from reference and citation iterations'), records, link='prisma-autres-methodes.csv'))
             + row(box(o['records'], screened, records),
                   box(o['titles_excluded'], title_ex, records, low_note(o, _(', then excluded in duplicate on abstract')), ' out'))
             + row(box(o['abstracts'], abstracts, records),
                   box(o['abstracts_excluded'], abstract_ex, records, kind=' out')))
    merged = (row(box(f['reports_sought'], _('Reports sought'), reports,
                      '<small>' + _('{databases} from databases + {other} from other methods', databases=fmt(f["reports_sought_from_databases"]), other=fmt(f["other_methods"]["reports_sought"])) + '</small>'),
                  box(f['reports_not_retrieved'], _('Not retrieved'), reports, '<small>' + _('no usable abstract or text; these are not exclusions') + '</small>', ' side', 'prisma-non-recuperees.csv'))
              + row(box(f['reports_assessed'], _('Eligibility assessed in duplicate'), reports),
                    box(f['reports_excluded'], _('Excluded at eligibility'), reports, reasons(c['elig_codes']), ' out', 'prisma-exclues-eligibilite.csv'))
              + row(box(f['reports_included'], _('Reports included'), reports, kind=' in', link='prisma-incluses.csv'),
                    box(f['studies_included'], _('Unique studies included'), studies,
                        '<small>' + _('{secondary} secondary reports (registry, conference, thesis) linked to {linked} studies; cohort overlap not assessed',
                                      secondary=fmt(c["secondary"]), linked=fmt(c["linked"])) + '</small>', ' in')))
    return f'''<figure class="flow-diagram p0-prisma" id="flux" aria-labelledby="p0-prisma-caption"><figcaption id="p0-prisma-caption"><h3>{_('PRISMA 2020 flow diagram')}</h3>
        <p>{_('Every number is computed from the recorded decisions (scripts, reviewers A and B, adjudication), with no manual entry. Units: <strong>records</strong> (references after deduplication), <strong>reports</strong> (articles, conference abstracts, registry records assessed), <strong>studies</strong> (a study may have several reports).')}</p></figcaption>
        <div class="p0-prisma-grid"><div class="p0-col"><h4>{_('Databases and registers')}</h4>{db}</div><div class="p0-col"><h4>{_('Other methods')}</h4>{other}</div></div>
        <div class="p0-col p0-merged"><h4>{_('Eligibility and inclusion')}</h4>{merged}</div></figure>'''


# ---- GRADE by outcome -------------------------------------------------------------------------------------

def grade_summary(review, page):
    by_ref = {s['page_reference']: s for s in review['studies']}
    nr = _('n.r.')
    rows = []
    for o in review['grade']['outcomes']:
        refs = o.get('references', [])
        studies = [by_ref[r] for r in refs if r in by_ref]
        trials = [s for s in studies if s['randomized']]
        known = [s['randomized']['n'] for s in trials if isinstance(s['randomized']['n'], int)]
        participants = (f'{fmt(sum(known))}' + (f'<small class="p0-fn" title="{_("{n} trial(s) without reported sample size", n=len(trials) - len(known))}">+{len(trials) - len(known)} {nr}</small>' if len(known) < len(trials) else '')) if trials else '—'
        cells = []
        for key, label in GRADE_DOMAINS:
            d = o.get('domains', {}).get(key, {})
            r = d.get('rating')
            mark = {0: ('○', _('not downgraded')), -1: ('↓', _('downgraded one level')), -2: ('↓↓', _('downgraded two levels'))}.get(r, ('?', _('not assessed')))
            cells.append(f'<td class="p0-g{abs(r) if isinstance(r, int) else "x"}" title="{labelled(escape(_(label)), mark[1] + " — " + escape(d.get("reason", "")))}"><span aria-hidden="true">{mark[0]}</span><span class="sr">{mark[1]}</span></td>')
        reasons = ''.join(f'<li>{labelled("<strong>" + escape(_(label)) + "</strong>", escape(o["domains"][key]["reason"]))}</li>'
                          for key, label in GRADE_DOMAINS if o.get('domains', {}).get(key, {}).get('rating'))
        # "critique" is the importance value as stored in the review data.
        rows.append(f'''<tr><th scope="row"><span class="p0-oid">{escape(o["id"])}</span> {escape(o["label"])}<details><summary>{_('Reasons and statement')}</summary><p>{escape(o.get("statement", ""))}</p><ul>{reasons}</ul></details></th>
            <td>{"critique" if o.get("importance") == "critique" else escape(o.get("importance", ""))}</td><td>{fmt(len(refs))}</td><td>{fmt(len(trials))}</td><td>{participants}</td>
            {"".join(cells)}<td><span class="p0-cert p0-cert-{escape(o.get("certainty", "").replace(" ", "-"))}">{escape(o.get("certainty", _("not assessed")))}</span></td></tr>''')
    head = ''.join(f'<th scope="col" class="p0-dom"><abbr title="{escape(_(label))}">{escape(short)}</abbr></th>' for (_k, label), short in zip(GRADE_DOMAINS, (_('Bias'), _('Inconsistency'), _('Indirect'), _('Imprecision'), _('Publication'))))
    return f'''<div class="p0-block" id="grade-synthese"><h3>{_('GRADE in numbers')}</h3><p class="p0-lead">{_('For each outcome: contributing studies, randomized trials and participants, downgraded domains. The full rationale is in the “Certainty of evidence” section.')}</p>
        <div class="study-context"><div class="table-scroll" role="region" tabindex="0" aria-label="{_('GRADE by outcome')}"><table class="p0-table p0-grade"><caption>{_('Certainty, number of studies and participants, by outcome')}</caption><thead><tr><th scope="col">{_('Outcome')}</th><th scope="col">{_('Importance')}</th><th scope="col">{_('Studies')}</th><th scope="col">{_('Rand. trials')}</th><th scope="col">{_('Rand. participants')}</th>{head}<th scope="col">{_('Certainty')}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>
        <p class="table-note">{_('○ not downgraded · ↓ downgraded one level · ↓↓ two levels. No pooled effect is calculated: narrative synthesis, without meta-analysis (No pooled effect calculated). Participants: sum of the reported randomized sample sizes; “n.r.” = trials without a reported sample size, not counted. GRADE domains: risk of bias, inconsistency, indirectness, imprecision, publication bias.')}</p></div>'''


# ---- Filterable table of studies --------------------------------------------------------------------------

def study_rows(review, page):
    rob = {x['page_reference']: x for x in review['risk_of_bias']}
    access = {x['study']: x['access'] for x in review['reports'] if x['role'] == 'primary_report'}
    for s in sorted(review['studies'], key=lambda s: (s['year'] or 0, s['label'])):
        r = rob.get(s['page_reference'], {})
        yield s, r, access.get(s['id'], 'unknown'), page['studies'][s['page_reference']]


def study_explorer(review, page, base):
    outcomes = [o['id'] for o in review['outcomes']]
    rows = []
    for s, r, acc, ps in study_rows(review, page):
        level = overall_level(r) if r.get('tool') != 'Non évaluable' else 'na'  # tool value of the review data
        lv = LEVEL.get(level, (N_('Not assessable'), '–'))
        trial = f'{fmt(s["randomized"]["n"])}' if s['randomized'] and isinstance(s['randomized']['n'], int) else (_('n.r.') if s['randomized'] else '')
        rows.append(f'''<tr data-kind="{s['kind']}" data-access="{acc}" data-rob="{level}" data-outcomes="{' '.join(s['outcomes'])}" data-rct="{'1' if s['randomized'] else '0'}">
            <th scope="row"><a href="#{s['page_reference']}">{escape(s['label'])}</a></th><td>{escape(s['design'])}</td><td>{_(KIND[s['kind']])}</td>
            <td>{_(ACCESS[acc]) if acc in ACCESS else acc}</td><td>{trial}</td><td>{' '.join(s['outcomes'])}</td>
            <td class="p0-robcell"><span class="p0-rob p0-rob-{level}" title="{escape(r.get('overall', ''))}">{lv[1]}</span><span><strong>{escape(_(lv[0]))}</strong><small>{escape(r.get('tool') or '') if level != 'na' else _('registry record without results')}</small></span></td></tr>''')
    opt = lambda items: ''.join(f'<option value="{k}">{escape(v)}</option>' for k, v in items)
    every = _('All')
    return f'''<div class="p0-block p0-explorer" id="etudes-incluses" data-explorer><h3>{_('Table of included studies')}</h3>
        <div class="p0-filters" role="group" aria-label="{_('Filters')}">
          <label class="p0-select"><span>{_('Type')}</span><select data-filter="kind"><option value="">{every}</option>{opt((k, _(v)) for k, v in KIND.items())}</select></label>
          <label class="p0-select"><span>{_('Outcome')}</span><select data-filter="outcomes"><option value="">{every}</option>{opt((o, o) for o in outcomes)}</select></label>
          <label class="p0-select"><span>{_('Risk of bias')}</span><select data-filter="rob"><option value="">{every}</option>{opt([(k, _(v[0])) for k, v in LEVEL.items()] + [('na', _('Not assessable'))])}</select></label>
          <label class="p0-select"><span>{_('Source read')}</span><select data-filter="access"><option value="">{_p('source', 'All')}</option>{opt((k, _(v)) for k, v in ACCESS.items())}</select></label>
          <label class="p0-check"><input type="checkbox" data-filter="rct" value="1"> {_('Randomized trials')}</label>
          <span class="p0-count" aria-live="polite"></span><a class="p0-button" href="{base}/etudes.csv" download>{_('Export (CSV)')}</a></div>
        <div class="study-context"><div class="table-scroll" role="region" tabindex="0" aria-label="{_('Included studies')}"><table class="p0-table p0-studies"><caption>{_('Included studies · filters above')}</caption><thead><tr><th scope="col">{_('Study')}</th><th scope="col">{_('Design')}</th><th scope="col">{_('Type')}</th><th scope="col">{_('Source read')}</th><th scope="col">{_('Randomized')}</th><th scope="col">{_('Outcomes')}</th><th scope="col">{_('Risk of bias')}</th></tr></thead>
        <tbody>{"".join(rows)}</tbody></table></div></div>
        <p class="table-note">{_('{n} unique studies. “n.r.”: randomized sample size not reported. The details (population, result, limitation) are in the tables of each section.', n=len(rows))}</p></div>'''


# ---- Risk of bias by study and by domain ------------------------------------------------------------------

def rob_matrix(review, page):
    rob = {x['page_reference']: x for x in review['risk_of_bias']}
    groups = OrderedDict()
    for s, r, acc, ps in study_rows(review, page):
        if r.get('tool') and r['tool'] != 'Non évaluable':
            groups.setdefault(r['tool'], []).append((s, r))
    blocks = []
    for tool in sorted(groups, key=lambda t: {'RoB 2': 0, 'ROBINS-I': 1}.get(t, 2)):
        items = groups[tool]
        width = max(len(r['domains']) for _s, r in items)
        names = Counter()
        for _s, r in items:
            if len(r['domains']) == width:
                names[tuple(d['name'] for d in r['domains'])] += 1
        header = names.most_common(1)[0][0]
        head = ''.join(f'<th scope="col"><span class="p0-dn">D{i + 1}</span> {escape(n)}</th>' for i, n in enumerate(header))
        rows = []
        for s, r in items:
            cells = []
            for i in range(width):
                d = r['domains'][i] if i < len(r['domains']) else None
                if not d:
                    cells.append('<td>–</td>')
                    continue
                lv = judgement_level(d['judgement'])
                cells.append(f'<td><span class="p0-rob p0-rob-{lv}" title="{labelled(escape(d["name"]), escape(d["judgement"]))}" tabindex="0">{LEVEL[lv][1]}</span><span class="sr">{escape(d["judgement"])}</span></td>')
            lv = overall_level(r)
            rows.append(f'''<tr data-outcomes="{' '.join(s['outcomes'])}"><th scope="row"><a href="#{s['page_reference']}">{escape(s['label'])}</a></th>{"".join(cells)}
                <td><span class="p0-rob p0-rob-{lv}">{LEVEL[lv][1]}</span> {escape(r.get('overall', ''))}<details><summary>{_('Rationale')}</summary><p>{escape(r.get('rationale', ''))}</p></details></td></tr>''')
        blocks.append(f'''<div class="study-context"><div class="table-scroll" role="region" tabindex="0" aria-label="{_('Risk of bias, {tool}', tool=escape(tool))}"><table class="p0-table p0-robm"><caption>{_('{tool} · {n} studies', tool=escape(tool), n=len(items))}</caption>
            <thead><tr><th scope="col">{_('Study')}</th>{head}<th scope="col">{_('Overall')}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>''')
    outcomes = ''.join(f'<option value="{o["id"]}">{escape(o["id"])} · {escape(o["label"][:60])}</option>' for o in review['outcomes'])
    legend = ''.join(f'<span class="p0-legend-item"><span class="p0-rob p0-rob-{k}">{v[1]}</span>{_(v[0])}</span>' for k, v in LEVEL.items())
    return f'''<div class="p0-block" id="risque-biais" data-robm><h3>{_('Risk of bias by study and by domain')}</h3>
        <p class="table-note">{_('Categories specific to each tool, never mixed across tools. For AMSTAR 2 and JBI, “yes” is shown as + and “no” as −. Hovering over or selecting a dot shows the judgment; the rationale can be expanded.')}</p>
        <div class="p0-filters"><label class="p0-select"><span>{_('Outcome')}</span><select data-filter="outcomes"><option value="">{_('All outcomes')}</option>{outcomes}</select></label></div>
        <p class="p0-legend">{legend}</p>{"".join(blocks)}
        <p class="table-note">{_('Studies not assessable (registry records without results): {n}.', n=sum(1 for x in rob.values() if x["tool"] == "Non évaluable"))}</p></div>'''


# ---- P1: evidence overview, gap map, audit, accessibility, risk of bias summary, reproducibility -------------

def nd():
    return f'<span class="p0-nd">{_("not available")}</span>'


DESIGN_GROUPS = [('rct', N_('Randomized trials')), ('nonrct', N_('Non-randomized primary studies')), ('sr', N_('Systematic reviews')), ('registry', N_('Registry records'))]


def pct(n, d):
    return _('{n}%', n=round(100 * n / d)) if d else _('not available')


def design_group(s):
    if s['kind'] == 'primary':
        return 'rct' if s['randomized'] else 'nonrct'
    return {'systematic_review': 'sr', 'registry': 'registry'}.get(s['kind'], 'other')


def primary_access(review):
    return {x['study']: x['access'] for x in review['reports'] if x['role'] == 'primary_report'}


def evidence_overview(review):
    studies = review['studies']
    kinds = Counter(s['kind'] for s in studies)
    trials = [s for s in studies if s['kind'] == 'primary' and s['randomized']]
    known = [s['randomized']['n'] for s in trials if isinstance(s['randomized']['n'], int)]
    years = [s['year'] for s in studies if s['year']]
    acc = primary_access(review)
    read = [acc.get(s['id'], 'unknown') for s in studies if s['kind'] != 'registry']
    full, abstract = read.count('full_text'), read.count('abstract')
    tile = lambda big, label, small='': f'<li class="method-tile"><strong>{big}</strong><span>{escape(label)}</span>{f"<small>{small}</small>" if small else ""}</li>'
    nr = len(trials) - len(known)
    tiles = [tile(fmt(len(studies)), _('Unique studies included'), _('{n} reports assessed, including linked duplicates', n=fmt(len(review["reports"])))),
             tile(fmt(kinds['primary']), _('Primary studies'), _('including {randomized} randomized and {other} non-randomized', randomized=fmt(len(trials)), other=fmt(kinds["primary"] - len(trials)))),
             tile(fmt(kinds['systematic_review']), _('Systematic reviews'), _('syntheses of trials or studies, not counted again among the trials')),
             tile(fmt(kinds['registry']), _('Registry records'), _('trials without published results')),
             tile(fmt(len(trials)), _('Randomized trials'), _('out of the {n} primary studies', n=fmt(kinds['primary']))),
             tile(fmt(sum(known)), _('Randomized participants (at least)'), _('sum of the reported sample sizes; {n} trial(s) without sample size (n.r.), not counted', n=nr) if nr else _('sum of the reported sample sizes')),
             tile(f'{min(years)}–{max(years)}' if years else _('not available'), _('Publication years'), _('{n} of {total} studies dated', n=len(years), total=len(studies))),
             tile(pct(full, len(read)), _('Read in full text'), _('{full} of {total} studies excluding registry records; {abstract} on abstract only', full=fmt(full), total=fmt(len(read)), abstract=fmt(abstract)))]
    return f'''<div class="p0-block" id="vue-ensemble"><h3>{_('Overview of the evidence')}</h3>
        <p class="p0-lead">{_('Counts computed from the structured review. Systematic reviews summarise other studies: they are not added to the trials.')}</p>
        <ul class="p0-tiles">{"".join(tiles)}</ul>
        <p class="table-note">{_('Randomized participants: sample sizes of trials only, sum of the reported sample sizes (overlap between studies not assessed).')}</p></div>'''


def gap_map(review):
    cells = {(o['id'], g): [] for o in review['outcomes'] for g, _l in DESIGN_GROUPS}
    for s in review['studies']:
        g = design_group(s)
        for o in s['outcomes']:
            if (o, g) in cells:
                cells[(o, g)].append(s)
    head = ''.join(f'<th scope="col">{escape(_(l))}</th>' for _g, l in DESIGN_GROUPS)
    rows = []
    for o in review['outcomes']:
        tds = []
        for g, l in DESIGN_GROUPS:
            n = len(cells[(o['id'], g)])
            tds.append(f'<td class="p0-gap p0-gap-{min(n, 4)}" title="{_("{outcome} · {design}: {n} study(ies)", outcome=escape(o["id"]), design=escape(_(l)), n=n)}"><strong>{n}</strong></td>' if n else
                       f'<td class="p0-gap p0-gap-0" title="{_("No study identified by this search")}"><span class="p0-zero">0</span></td>')
        total = len({s['id'] for g, _l in DESIGN_GROUPS for s in cells[(o['id'], g)]})
        rows.append(f'<tr><th scope="row"><span class="p0-oid">{escape(o["id"])}</span> {escape(o["label"])}</th>{"".join(tds)}<td class="p0-gap"><strong>{total}</strong></td></tr>')
    return f'''<div class="p0-block" id="carte-lacunes"><h3>{_('Gap map: outcomes and study types')}</h3>
        <p class="p0-lead">{_('Number of included studies reporting each protocol outcome, by study type. A study may count for several outcomes.')}</p>
        <div class="study-context"><div class="table-scroll" role="region" tabindex="0" aria-label="{_('Gap map')}"><table class="p0-table p0-gapmap"><caption>{_('Studies by outcome (O1 to O7) and by study type')}</caption>
        <thead><tr><th scope="col">{_('Outcome')}</th>{head}<th scope="col">{_('Distinct studies')}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>
        <p class="table-note">{_('A cell at “0” means that no study was identified by this search (databases searched and dates given in “Reproducibility”), not that no literature exists. The last column counts each study only once.')}</p></div>'''


def source_accessibility(review):
    acc = primary_access(review)
    studies = review['studies']
    c = Counter(acc.get(s['id'], 'unknown') for s in studies)
    nr = review['flow']['reports_not_retrieved']
    parts = [('full_text', _('Full text'), c['full_text']), ('abstract', _('Abstract only'), c['abstract']), ('registry', _('Registry record'), c['registry']),
             ('unknown', _('Source not specified'), c['unknown'] + c['title_only']), ('notret', _('Report not retrieved'), nr)]
    parts = [p for p in parts if p[2]]
    total = sum(p[2] for p in parts)
    segs = ''.join(f'<span class="p0-seg p0-seg-{k}" style="flex:{n}" title="{labelled(escape(l), n)}"><b>{n}</b></span>' for k, l, n in parts)
    legend = ''.join(f'<li><span class="p0-sw p0-seg-{k}"></span>{labelled(escape(l), f"<strong>{n}</strong> ({pct(n, total)})")}</li>' for k, l, n in parts)
    return f'''<div class="p0-block" id="accessibilite"><h3>{_('Accessibility of sources')}</h3>
        <p class="p0-lead">{_('Source actually read for each of the {n} included studies, plus the reports sought but not retrieved.', n=fmt(len(studies)))}</p>
        <div class="p0-bar" role="img" aria-label="{escape('; '.join(_('{label}: {n} of {total}', label=l, n=n, total=total) for _k, l, n in parts))}">{segs}</div>
        <ul class="p0-bar-legend">{legend}</ul>
        <p class="table-note">{_('Denominator: {total} = {studies} included studies + {not_retrieved} report(s) not retrieved (no usable abstract or text; neither included nor excluded). A study read on its abstract only is assessed with less certainty: this feeds the “not reported” domains of the risk of bias.', total=fmt(total), studies=fmt(len(studies)), not_retrieved=fmt(nr))}</p></div>'''


def rob_summary(review):
    groups = OrderedDict()
    for x in review['risk_of_bias']:
        if x.get('tool') and x['tool'] != 'Non évaluable':
            groups.setdefault(x['tool'], []).append(x)
    legend = ''.join(f'<span class="p0-legend-item"><span class="p0-rob p0-rob-{k}">{v[1]}</span>{_(v[0])}</span>' for k, v in LEVEL.items())
    overall = _('Overall judgment')
    blocks = []
    for tool in sorted(groups, key=lambda t: {'RoB 2': 0, 'ROBINS-I': 1}.get(t, 2)):
        items = groups[tool]
        doms = OrderedDict()
        width = Counter(len(x['domains']) for x in items).most_common(1)[0][0]
        full = [x for x in items if len(x['domains']) == width]
        for i in range(width):  # domains aligned by position, most frequent label
            label = Counter(x['domains'][i]['name'] for x in full).most_common(1)[0][0]
            doms[label] = Counter(judgement_level(x['domains'][i]['judgement']) for x in full)
        doms[overall] = Counter(overall_level(x) for x in items)

        def bar(cnt):
            n = sum(cnt.values())
            return ''.join(f'<span class="p0-seg p0-rob-{k}" style="flex:{cnt[k]}" title="{_("{label}: {n} of {total}", label=_(LEVEL[k][0]), n=cnt[k], total=n)}"><b>{LEVEL[k][1]} {cnt[k]}</b></span>' for k in LEVEL if cnt[k]), n
        rows = []
        for name, cnt in doms.items():
            b, n = bar(cnt)
            txt = ', '.join(f'{_(LEVEL[k][0]).lower()} {cnt[k]}' for k in LEVEL if cnt[k])
            rows.append(f'<li class="{"p0-total" if name == overall else ""}"><span class="p0-bl">{escape(name)}</span><span class="p0-bar" role="img" aria-label="{_("{label}: {n} of {total}", label=escape(name), n=txt, total=n)}">{b}</span><span class="p0-bn">n = {n}</span></li>')
        blocks.append(f'<div class="p0-robsum"><h4>{_("{tool} · {n} studies", tool=escape(tool), n=len(items))}</h4><ul>{"".join(rows)}</ul></div>')
    na = sum(1 for x in review['risk_of_bias'] if x.get('tool') == 'Non évaluable')
    return f'''<div class="p0-block" id="synthese-biais"><h3>{_('Risk of bias: summary by tool and by domain')}</h3>
        <p class="p0-lead">{_('Distribution of judgments by domain, separately for each tool. The tools are not comparable with each other and are never mixed.')}</p>
        <p class="p0-legend">{legend}</p>{"".join(blocks)}
        <p class="table-note">{_('Each bar: number of studies by level, n = studies assessed with the tool. “Unclear” groups the domains not reported (often because only the abstract was read). For AMSTAR 2, “yes” is shown as + and “no” as −. Bars by domain: studies whose tool form has the most common number of domains (n ≤ studies of the tool if some records have a different form); the overall judgment counts all studies. Studies not assessable (registry records without results): {n}, outside these bars.', n=na)}</p></div>'''


CLAIM_STATUS = {'in_progress': N_('in progress'), 'passed': N_('passed'), 'failed': N_('failed'), 'blocked': N_('blocked')}


def methodological_audit(review):
    a = review['audit']
    ag = a['agreement']
    labels = {'titles': _('Title screening'), 'abstracts': _('Abstract screening'), 'fulltext': _('Eligibility (reports)'), 'rob': _('Risk of bias (overall judgment)')}
    rows = ''.join(f'<tr><th scope="row">{escape(labels.get(k, k))}</th><td>{fmt(v["n"])}</td><td>{_("{n}%", n=format(v["agreement"] * 100, ".1f"))}</td><td>{v["kappa"]:.2f}</td>'
                   f'<td>{fmt(v["disagreements"]) if "disagreements" in v else fmt(round(v["n"] * (1 - v["agreement"])))}</td></tr>' for k, v in ag.items())
    evaluable = sum(1 for x in review['risk_of_bias'] if x.get('tool') != 'Non évaluable')
    rob_n = ag.get('rob', {}).get('n')
    pre = a.get('prefilter', {})
    sd = review['screening_decisions']
    low_read = sum(1 for d in sd if d['stage'] == 'prefilter-low-zone')
    low_kept = sum(1 for d in sd if d['stage'] == 'prefilter-low-zone' and d['decision'] == 'include')
    lost = pre.get('llm_audit', {}).get('eligible_lost')
    prefilter = [(_('Records in the low zone of the pre-filter'), fmt(pre.get('excluded_by_title_prefilter', low_read))), (_('Read once (title + abstract)'), fmt(low_read)),
                 (_('Kept after reading'), fmt(low_kept)), (_('Eligible records lost by the pre-filter'), fmt(pre['llm_audit']['eligible_lost']) if isinstance(lost, int) else None)]
    pre_html = ''.join(f'<li class="method-tile"><span>{escape(k)}</span><strong>{v}</strong></li>' if v is not None else f'<li class="method-tile"><span>{escape(k)}</span><small>{_("not measured")}</small></li>' for k, v in prefilter)
    cl = review['claims']
    rep = cl.get('report') or {}
    verdicts = rep.get('verdicts', {})
    vtxt = ' · '.join(labelled(escape(k), fmt(v)) for k, v in verdicts.items())
    st = cl.get('status')
    status = _(CLAIM_STATUS[st]) if st in CLAIM_STATUS else (st or _('not available'))
    passed = {True: _('yes'), False: _('no')}.get(rep.get('passed'), _('not available'))
    na = _('not available')
    return f'''<div class="p0-block" id="audit-methodologique"><h3>{_('Methodological audit')}</h3>
        <p class="p0-lead">{_('Agreement between the two AI reviewers (A and B) at each stage, before adjudication.')}</p>
        <div class="study-context"><div class="table-scroll" role="region" tabindex="0" aria-label="{_('Agreement by stage')}"><table class="p0-table p0-audit"><caption>{_('Agreement between reviewers by stage')}</caption>
        <thead><tr><th scope="col">{_('Stage')}</th><th scope="col">{_('Double assessments (n)')}</th><th scope="col">{_('Observed agreement')}</th><th scope="col">{_('Cohen’s kappa')}</th><th scope="col">{_('Disagreements')}</th></tr></thead><tbody>{rows}</tbody></table></div></div>
        <p class="table-note">{_('Kappa is descriptive: it measures the agreement between two AI reviewers, not the accuracy of the decisions. High agreement does not rule out a shared error. Risk of bias: {n} double assessments out of {total} assessable studies ({pct}); the others (including registry records) have a single reviewer.', n=fmt(rob_n) if rob_n is not None else na, total=fmt(evaluable), pct=pct(rob_n, evaluable) if rob_n is not None else na)}</p>
        <h4 class="p0-sub">{_('Pre-filter')}</h4><ul class="p0-tiles">{pre_html}</ul>
        <h4 class="p0-sub">{_('Claim verification')}</h4>
        <p class="p0-claims">{_('Status: <strong>{status}</strong> · {claims} claims · {pairs} claim-source pairs checked · check passed: {passed}.', status=escape(status), claims=fmt(cl.get("n_claims")), pairs=fmt(rep.get("pairs")), passed=passed)}<br>{vtxt or nd()}</p>
        <p class="table-note">{_('Each numerical claim of the page is compared with its source by an AI agent; “partially supports” and “does not support” call for a correction or a softening before the “verified” label.')}</p></div>'''


def reproducibility(review):
    r = review['review']
    prot = review['protocol']
    pdata = json.loads((ROOT / prot['path']).read_text(encoding='utf-8'))
    profile_path = METHODOLOGY / 'profiles' / f'{r["review_depth"]}.json'
    profile = json.loads(profile_path.read_text(encoding='utf-8')) if profile_path.exists() else {}
    ex = review['execution']
    tok = ex.get('tokens') or {}
    cov = (profile.get('extraction') or {}).get('double_extraction_coverage')
    evaluable = sum(1 for x in review['risk_of_bias'] if x.get('tool') != 'Non évaluable')
    rob_n = review['audit']['agreement'].get('rob', {}).get('n')
    devs = prot.get('deviations') or []
    dev_html = ''.join(f'<li>{labelled("<strong>" + escape(d.get("date", "")) + "</strong>", escape(d.get("change", "")))}<br><small>{_("Reason: {reason}", reason=escape(d.get("reason", "")))}</small></li>' for d in devs)
    sources = ''.join(f'<li>{escape(s)}</li>' for s in pdata.get('sources', []))
    ext = prot.get('external_registration')
    na = _('not available')
    n = lambda v: fmt(v) if isinstance(v, int) else na
    dd = lambda k, v: f'<div><dt>{escape(k)}</dt><dd>{v}</dd></div>'
    meth = [dd(_('Methodology version (profile)'), escape(str(profile.get('methodology_version', na)))),
            dd(_('Methodology version when the review was produced'), f'{escape(str(r["methodology_version"]))}' + (_(' (migrated with {version})', version=escape(str(r["migrated_with_methodology"]))) if r.get('migrated_with_methodology') else '')),
            dd(_('Data format (schema)'), escape(str(review['schema_version']))),
            dd(_('Protocol committed'), _('<code>{commit}</code> on {date}', commit=escape(prot["commit"][:7]), date=escape(prot["committed_at"])) if prot.get('commit') else na),
            dd(_('Protocol status'), escape(prot.get('status', na))),
            dd(_('External registration'), escape(str(ext)) if ext else _('not registered outside Git')),
            dd(_('Search date'), escape(r['search_date'])),
            dd(_('Requested rigour profile'), labelled(f'<strong>{escape(r["review_depth"])}</strong>', escape(_(profile["description"]) if profile.get("description") else _("profile not available")))),
            dd(_('Double extraction planned / achieved'), _('planned: {coverage} of studies', coverage=_('{n}%', n=format(cov * 100, '.0f')) if isinstance(cov, (int, float)) else na)
               + (_(' (always double for critical outcomes)') if (profile.get('extraction') or {}).get('always_double') else '')
               + _('; risk of bias in duplicate: {n} of {total} ({pct})', n=n(rob_n), total=n(evaluable), pct=pct(rob_n, evaluable) if rob_n is not None else na)),
            dd(_('Models'), escape(ex.get('models') or na)),
            dd(_('Tokens used (a posteriori estimate, approximate attribution)'),
               _('output: {output} · cache read: {cache_read} · cache write: {cache_write} · input: {input} · messages: {messages}',
                 output=n(tok.get("output_tokens")), cache_read=n(tok.get("cache_read_input_tokens")), cache_write=n(tok.get("cache_creation_input_tokens")),
                 input=n(tok.get("input_tokens")), messages=n(tok.get("messages")))
               if tok else na),
            dd(_('Cost'), _('{amount} USD', amount=ex["cost_usd"]) if ex.get('cost_usd') is not None else _('not calculated (unknown, not zero)')),
            dd(_('Duration'), _('{n} s', n=ex["duration_seconds"]) if ex.get('duration_seconds') is not None else _p('duration', 'not measured'))]
    return f'''<div class="p0-block" id="reproductibilite"><h3>{_('Reproducibility')}</h3>
        <p class="p0-lead">{_('What makes it possible to re-check this review, and what does not.')}</p>
        <dl class="p0-dl">{"".join(meth)}</dl>
        <div class="p0-two"><div><h4 class="p0-sub">{_('Sources searched')}</h4><ul class="p0-plain">{sources}</ul></div>
        <div><h4 class="p0-sub">{_('Sources not searched')}</h4><p class="p0-plain">{escape(pdata.get("not_searched", na))}</p></div></div>
        <details class="p0-dev"><summary>{_('{n} protocol deviation(s)', n=len(devs))}</summary><ul class="p0-plain">{dev_html or "<li>" + _("None") + "</li>"}</ul></details>
        <p class="table-note">{_('<strong>Deterministic reproducibility</strong>: all the tables, charts and counts of this page are recomputed identically from the <code>review.json</code> file of the open data package. <strong>Probabilistic repeatability</strong>: a new run of the AI agents (screening, extraction, GRADE) may give different decisions; it is not guaranteed by this package. Tokens are an a posteriori estimate from the session logs, with approximate attribution by keywords.')}</p></div>'''


# ---- Downloads --------------------------------------------------------------------------------------------

FILES = [('review.json', N_('Complete structured review (exchange format v0.8, schema included in the package)')),
         ('protocole.json', N_('Protocol registered before the search, with its deviations')),
         ('strategies-recherche.json', N_('Exact queries, dates and numbers of results')),
         ('selection.csv', N_('All selection decisions (reviewers A and B, adjudication, scripts)')),
         ('etudes.csv', N_('Included studies and linked reports')),
         ('risque-biais.csv', N_('Risk of bias by study and by domain')),
         ('grade.json', N_('GRADE by outcome and main statement')),
         ('audit.json', N_('Agreement (kappa), pre-filter audit, claim verification')),
         ('execution.json', N_('Models, tokens used (estimate), duration')),
         ('MANIFEST.json', N_('SHA-256 fingerprints, versions, licences'))]


def csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def columns(*names):
    """Translated CSV column names."""
    return [_p('csv', n) for n in names]


def export_package(subject):
    review = json.loads((ROOT / f'data/reviews/{subject}.json').read_text(encoding='utf-8'))
    page = json.loads(output_path(subject, 'data', ROOT).read_text(encoding='utf-8'))
    out = ROOT / config(ROOT).get('open_data_dir', 'open-data') / subject
    out.mkdir(parents=True, exist_ok=True)
    titles = {r['id']: r for r in review['records']}
    # File names are part of the published URLs: they are not translated.
    files = {
        'review.json': json.dumps(review, ensure_ascii=False, indent=1),
        'protocole.json': (ROOT / review['protocol']['path']).read_text(encoding='utf-8'),
        'strategies-recherche.json': json.dumps(review['searches'], ensure_ascii=False, indent=1),
        'selection.csv': csv_text(columns('record', 'title', 'year', 'stage', 'reviewer', 'decision', 'code', 'reason'),
                                  ([d['record'], titles.get(d['record'], {}).get('title'), titles.get(d['record'], {}).get('year'), d['stage'],
                                    d['reviewer'], d['decision'], d.get('code'), d.get('reason')] for d in review['screening_decisions'])),
        'etudes.csv': csv_text(columns('study', 'label', 'year', 'design', 'type', 'source_read', 'reports', 'randomized', 'outcomes', 'rob_tool', 'rob_overall', 'page_reference'),
                               ([s['id'], s['label'], s['year'], s['design'], s['kind'], acc, ' '.join(s['reports']),
                                 s['randomized']['n'] if s['randomized'] else '', ' '.join(s['outcomes']), r.get('tool'), r.get('overall'), s['page_reference']]
                                for s, r, acc, _ps in study_rows(review, page))),
        'risque-biais.csv': csv_text(columns('study', 'page_reference', 'tool', 'domain', 'judgement', 'overall', 'overall_level', 'extraction_level', 'rationale'),
                                     ([x['study'], x['page_reference'], x['tool'], d['name'], d['judgement'], x['overall'], overall_level(x), x['level'], x.get('rationale')]
                                      for x in review['risk_of_bias'] for d in (x['domains'] or [{'name': '', 'judgement': ''}]))),
        'grade.json': json.dumps(review['grade'], ensure_ascii=False, indent=1),
        'audit.json': json.dumps({'audit': review['audit'], 'claims': review['claims'], 'flow': review['flow']}, ensure_ascii=False, indent=1),
        'execution.json': json.dumps(review['execution'], ensure_ascii=False, indent=1),
    }
    # Lists behind the PRISMA boxes.
    main, other = branches(review)
    t, a, e = resolved(review, 'titles'), resolved(review, 'abstracts'), resolved(review, 'eligibility')
    low = {d['record'] for d in review['screening_decisions'] if d['stage'] == 'prefilter'} & main
    included = {r for s in review['studies'] for r in s['reports']}
    lists = {'prisma-notices.csv': main, 'prisma-zone-basse.csv': low, 'prisma-autres-methodes.csv': other,
             'prisma-exclues-titres.csv': {i for i in main if t.get(i, {}).get('decision') == 'exclude'},
             'prisma-exclues-resumes.csv': {i for i in main if a.get(i, {}).get('decision') == 'exclude'},
             'prisma-exclues-eligibilite.csv': {i for i, d in e.items() if d['decision'] == 'exclude'},
             'prisma-non-recuperees.csv': {i for i, d in e.items() if d['decision'] == 'not_retrieved'},
             'prisma-incluses.csv': {i for i, d in e.items() if d['decision'] == 'include'}}
    for name, ids in lists.items():
        files[name] = csv_text(columns('record', 'title', 'year', 'titles_decision', 'abstracts_decision', 'eligibility_decision', 'code'),
                               ([i, titles.get(i, {}).get('title'), titles.get(i, {}).get('year'), t.get(i, {}).get('decision'),
                                 a.get(i, {}).get('decision'), e.get(i, {}).get('decision'),
                                 (e.get(i) or a.get(i) or t.get(i) or {}).get('code')] for i in sorted(ids)))
    files['schema.json'] = (METHODOLOGY / 'schemas/review.schema.json').read_text(encoding='utf-8')
    files['README.txt'] = _('Open package of the review “{title}”\n'
                            'Methodology {methodology}, format {schema}, profile {profile}.\n\n'
                            'Deterministic reproduction: the tables, charts and counts of the page are recomputed from review.json\n'
                            '(scripts/render_p0.py, scripts/check_review.py of the repository). A new run of the AI agents (repeatability) may\n'
                            'give different decisions: it is not guaranteed by this package.\n\n'
                            'Not included: abstracts and full texts of the articles (publishers’ rights); only the identifiers (PMID, DOI,\n'
                            'NCT, Europe PMC) and the provenance are published.\n\n'
                            'Licences: data (CSV, JSON) CC0 1.0; synthesis texts (GRADE statements, rationales) CC BY 4.0;\n'
                            'repository code Apache-2.0.\n',
                            title=review["review"]["title"], methodology=review["review"]["methodology_version"],
                            schema=review["schema_version"], profile=review["review"]["review_depth"])
    manifest = {'review': subject, 'schema_version': review['schema_version'], 'methodology_version': review['review']['methodology_version'],
                'licences': {'data': 'CC0-1.0', 'text': 'CC-BY-4.0', 'code': 'Apache-2.0'},
                'files': {n: {'sha256': hashlib.sha256(c.encode()).hexdigest(), 'bytes': len(c.encode())} for n, c in sorted(files.items())}}
    files['MANIFEST.json'] = json.dumps(manifest, ensure_ascii=False, indent=1)
    for name, content in files.items():
        (out / name).write_text(content, encoding='utf-8')
    with zipfile.ZipFile(out / 'paquet-revue.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in sorted(files.items()):
            z.writestr(f'{subject}/{name}', content)
    return out


def downloads(subject, base):
    out = ROOT / config(ROOT).get('open_data_dir', 'open-data') / subject
    size = lambda n: _('{n} KB', n=max(1, (out / n).stat().st_size // 1024)) if (out / n).exists() else ''
    items = ''.join(f'<li class="method-tile"><a href="{base}/{n}" download>{escape(n)}</a><small>{size(n)} · {escape(_(d))}</small></li>' for n, d in FILES)
    return f'''<div class="p0-block" id="telechargements"><h3>{_('Open data')}</h3>
        <p><a class="p0-button" href="{base}/paquet-revue.zip" download>{_('Download the full package · .zip, {size}', size=size("paquet-revue.zip"))}</a></p>
        <ul class="p0-files">{items}</ul>
        <p class="table-note">{_('Data under a CC0 licence, synthesis texts under CC BY 4.0. The abstracts and full texts of the articles are not redistributed (publishers’ rights): only their identifiers and provenance are.')}</p></div>'''


STYLE = '''<style>
.p0-block{margin:34px 0 0}.p0-block>h3{font:400 24px Georgia,serif;color:var(--foreground);margin-bottom:6px}.p0-lead{font-size:13px;color:var(--muted);max-width:760px;margin:0 0 12px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.p0-prisma-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px;margin-top:16px}.p0-col{display:flex;flex-direction:column;gap:10px;min-width:0}
.p0-col h4{margin:0 0 2px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.p0-merged{margin-top:18px}
.p0-prisma .flow-box{height:auto}.p0-prisma .flow-box strong{font-size:20px}.p0-reasons abbr{text-decoration:none;font-weight:700}
.p0-robcell{display:flex;gap:8px;align-items:center}.p0-robcell small{display:block;font-size:11px;color:var(--muted)}.p0-robcell strong{font-size:12px}.p0-unit{display:inline-block;margin-top:4px;font-size:10px;font-style:normal;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.p0-prisma .flow-box small{display:block;color:var(--muted);margin-top:4px}.p0-reasons{margin:6px 0 0;padding-left:16px;font-size:11px;color:var(--muted)}
.p0-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}.p0-row>span{display:block}
.p0-list{display:block;width:max-content;margin-top:6px;font-size:11px;font-weight:700;color:var(--primary)}
.p0-filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0 14px}
.p0-select,.p0-check{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:20px;background:var(--card);padding:5px 6px 5px 12px;font-size:12px;font-weight:700;color:var(--foreground)}
.p0-check{padding-right:12px;cursor:pointer}.p0-check input{accent-color:var(--primary);margin:0}
.p0-select>span{color:var(--muted);font-weight:400}.p0-select:focus-within,.p0-check:focus-within{border-color:var(--primary)}
.p0-select select{appearance:none;-webkit-appearance:none;border:0;background:var(--secondary) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23176b64' stroke-width='1.5'/%3E%3C/svg%3E") no-repeat right 10px center;border-radius:14px;padding:4px 28px 4px 10px;font:700 12px var(--font-sans);color:var(--primary);cursor:pointer;max-width:220px}
.p0-select select:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.p0-count{font-size:12px;color:var(--muted);margin-left:auto}
.p0-button{display:inline-block;border:1px solid var(--primary);border-radius:24px;padding:7px 16px;background:var(--card);color:var(--primary);font-size:12px;font-weight:700;text-decoration:none}.p0-button:hover{background:var(--secondary)}
.study-context .p0-table th,.study-context .p0-table td{width:auto;padding:10px 12px}.p0-table{min-width:720px}.p0-table td{vertical-align:middle}
.p0-studies tbody th a{font-weight:700}.p0-robm thead th{vertical-align:bottom;font-size:11px;font-weight:700;color:var(--muted);min-width:90px}.p0-robm tbody th{min-width:150px}
.p0-robm td{text-align:center}.p0-robm td:last-child{text-align:left;min-width:200px}.p0-dn{display:block;color:var(--primary)}
.p0-rob{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;font-size:12px;font-weight:700;line-height:1;border:1.5px solid;vertical-align:middle}
.p0-rob-low{background:var(--primary);border-color:var(--primary);color:#fff}.p0-rob-some{background:var(--accent-surface);border-color:var(--warning);color:var(--warning)}
.p0-rob-high{background:var(--accent);border-color:var(--accent);color:#fff}.p0-rob-critical{background:#6e3511;border-color:#6e3511;color:#fff}
.p0-rob-unclear{background:var(--card);border-color:var(--muted);color:var(--muted);border-style:dashed}.p0-rob-na{background:var(--secondary);border-color:var(--border);color:var(--muted)}
.p0-legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12px;color:var(--muted);margin:0 0 12px}.p0-legend-item{display:inline-flex;align-items:center;gap:6px}
.p0-grade{table-layout:auto}.study-context .p0-grade td{text-align:center;font-size:12px;padding:10px 6px}.study-context .p0-grade th.p0-dom{font-size:11px;padding:10px 4px;text-align:center}.p0-dom abbr{text-decoration:none}.p0-grade tbody th{min-width:280px}.p0-fn{display:block;font-size:10px;color:var(--muted)}.p0-g1,.p0-g2{color:var(--accent);font-weight:700}.p0-gx{color:var(--muted)}.p0-oid{font-weight:700;color:var(--primary);margin-right:4px}
.p0-cert{display:inline-block;padding:3px 10px;border-radius:20px;border:1px solid var(--border);background:var(--secondary);font-weight:700;white-space:nowrap}
.p0-cert-très-faible,.p0-cert-faible{border-color:var(--accent);background:var(--accent-surface);color:var(--accent)}
.p0-files{list-style:none;padding:0;margin:14px 0 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}.p0-files .method-tile a{font-weight:700;font-size:13px;color:var(--primary)}
.p0-tiles{list-style:none;padding:0;margin:12px 0 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}.p0-tiles .method-tile small{display:block}
.p0-nd,.p0-zero{color:var(--muted)}.p0-sub{margin:22px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.p0-gapmap{min-width:640px}.study-context .p0-gapmap td{text-align:center;padding:10px 8px}.p0-gapmap tbody th{min-width:260px}.p0-gap strong{font-size:15px}.p0-gap-0{background:var(--card)}
.p0-gap-1{background:var(--secondary)}.p0-gap-2{background:var(--secondary)}.p0-gap-3,.p0-gap-4{background:var(--accent-surface)}
.p0-bar{display:flex;width:100%;min-height:28px;border:1px solid var(--border);border-radius:6px;overflow:hidden;background:var(--card)}
.p0-seg{display:flex;align-items:center;justify-content:center;min-width:0;padding:0 4px;font-size:12px;overflow:hidden;white-space:nowrap}.p0-seg+.p0-seg{border-left:2px solid #fff}
.p0-seg-full_text{background:var(--primary);color:#fff}.p0-seg-abstract{background:var(--accent-surface);color:var(--warning)}.p0-seg-registry{background:var(--secondary);color:var(--primary)}
.p0-seg-unknown,.p0-seg-notret{background:var(--card);color:var(--muted)}.p0-seg-notret{background:repeating-linear-gradient(45deg,var(--card),var(--card) 4px,var(--secondary) 4px,var(--secondary) 8px)}
.p0-bar .p0-rob-low,.p0-bar .p0-rob-some,.p0-bar .p0-rob-high,.p0-bar .p0-rob-critical,.p0-bar .p0-rob-unclear,.p0-bar .p0-rob-na{display:flex;width:auto;height:auto;border-radius:0;border:0;border-left:0}
.p0-bar .p0-rob-unclear{border-style:solid}
.p0-bar-legend{list-style:none;padding:0;margin:10px 0 0;display:flex;flex-wrap:wrap;gap:6px 20px;font-size:12px}.p0-sw{display:inline-block;width:12px;height:12px;border:1px solid var(--border);border-radius:3px;margin-right:6px;vertical-align:-1px}
.p0-robsum{margin:18px 0 0}.p0-robsum h4{margin:0 0 8px;font:400 18px Georgia,serif;color:var(--primary)}.p0-robsum ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
.p0-robsum li{display:grid;grid-template-columns:minmax(150px,260px) minmax(0,1fr) 54px;gap:10px;align-items:center;font-size:12px}.p0-robsum .p0-bn{color:var(--muted);text-align:right}.p0-robsum .p0-total .p0-bl{font-weight:700}
.p0-dl{margin:12px 0 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}.p0-dl>div{border:1px solid var(--border);border-radius:12px;padding:12px 14px;background:var(--card);min-width:0}
.p0-dl dt{font-size:11px;color:var(--muted);margin-bottom:3px}.p0-dl dd{margin:0;font-size:13px;overflow-wrap:anywhere}
.p0-two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}.p0-plain{font-size:13px;margin:0;padding-left:18px}.p0-plain li{margin-bottom:6px}p.p0-plain{padding:0}.p0-dev{margin-top:14px;font-size:13px}.p0-dev summary{cursor:pointer;font-weight:700;color:var(--primary)}
.p0-claims{font-size:13px;margin:0}
@media(max-width:900px){.p0-prisma-grid{grid-template-columns:1fr}}@media(max-width:560px){.p0-two{grid-template-columns:1fr}.p0-robsum li{grid-template-columns:1fr auto}.p0-robsum .p0-bar{grid-column:1/-1;order:3}.p0-dl{grid-template-columns:1fr}.p0-row{grid-template-columns:1fr}.p0-count{margin-left:0;flex-basis:100%}}
@media print{.p0-seg,.p0-rob,.p0-gap{-webkit-print-color-adjust:exact;print-color-adjust:exact}.p0-filters,.p0-list,.p0-button{display:none}.p0-block tr[hidden]{display:table-row}}
.p0-forest small{display:block;font-size:11px;color:var(--muted);font-weight:400}.p0-forest tbody th{min-width:190px}.p0-fp-cell{min-width:270px}
.p0-fp{width:260px;height:24px;display:block}.p0-fp-null{stroke:var(--muted);stroke-dasharray:3 3}.p0-fp-ci{stroke:var(--foreground);stroke-width:1.6}.p0-fp-pt{fill:var(--primary)}.p0-fp-arrow{fill:var(--foreground)}
.p0-fp-num{white-space:nowrap}.p0-fp-warn{color:var(--accent)!important;white-space:normal;max-width:220px}
</style>'''


def script():
    # The count of displayed studies is a JavaScript expression of `n`, so that each language handles its own plural.
    count = _("n+(n===1?' study shown':' studies shown')")
    return '''<script>
document.querySelectorAll('[data-explorer]').forEach(function(box){
  var rows=box.querySelectorAll('tbody tr'),count=box.querySelector('.p0-count'),filters=box.querySelectorAll('[data-filter]');
  function apply(){var n=0;rows.forEach(function(r){var ok=true;filters.forEach(function(f){var k=f.dataset.filter,v=f.type==='checkbox'?(f.checked?'1':''):f.value;
    if(v&&(' '+r.dataset[k]+' ').indexOf(' '+v+' ')<0)ok=false;});r.hidden=!ok;if(ok)n++;});count.textContent=''' + count + ''';}
  filters.forEach(function(f){f.addEventListener('change',apply);});apply();});
document.querySelectorAll('[data-robm]').forEach(function(box){var s=box.querySelector('select');s.addEventListener('change',function(){
  box.querySelectorAll('tbody tr').forEach(function(r){r.hidden=s.value&&(' '+r.dataset.outcomes+' ').indexOf(' '+s.value+' ')<0&&(' '+r.dataset.outcomes+' ').indexOf(' '+s.value.slice(0,2)+' ')<0;});});});
</script>'''


def __getattr__(name):
    # `SCRIPT` is rendered on access, in the current language.
    if name == 'SCRIPT':
        return script()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


if __name__ == '__main__':
    import sys
    print(export_package(sys.argv[1]))


# ---- Forest plot without pooling (P1) ---------------------------------------------------------------------

def forest_plot(review, page):
    """Effects by study, computed by script, with no diamond and no overall effect. RR on a common logarithmic scale
    per outcome; mean differences with a scale specific to each row (different units)."""
    est = review.get('effect_estimates', {})
    items = [e for e in est.get('items', []) if e.get('computed')]
    if not items:
        return ''
    labels = {s['id']: s for s in review['studies']}
    outcome_label = {o['id']: o['label'] for o in review['outcomes']}
    arms = est.get('arms') or DEFAULT_ARMS
    ki, kc = arms['intervention']['key'], arms['comparator']['key']
    W, X0, X1 = 260, 10, 250

    def ci_label(measure, c):
        # The accessible label keeps a decimal point in every language.
        return _('{measure} {value}, 95% CI {low} to {high}', measure=measure, value=f'{c["value"]:.2f}', low=f'{c["ci_low"]:.2f}', high=f'{c["ci_high"]:.2f}')

    def svg_rr(c):
        lo, hi = 0.05, 20.0
        pos = lambda v: X0 + (math.log(min(max(v, lo), hi)) - math.log(lo)) / (math.log(hi) - math.log(lo)) * (X1 - X0)
        one = pos(1)
        clip_l, clip_r = c['ci_low'] < lo, c['ci_high'] > hi
        return (f'<svg class="p0-fp" viewBox="0 0 {W} 24" role="img" aria-label="{ci_label("RR", c)}">'
                f'<line x1="{one:.1f}" y1="0" x2="{one:.1f}" y2="24" class="p0-fp-null"/>'
                f'<line x1="{pos(c["ci_low"]):.1f}" y1="12" x2="{pos(c["ci_high"]):.1f}" y2="12" class="p0-fp-ci"/>'
                + (f'<path d="M{X0} 12 l6 -4 v8z" class="p0-fp-arrow"/>' if clip_l else '') + (f'<path d="M{X1} 12 l-6 -4 v8z" class="p0-fp-arrow"/>' if clip_r else '')
                + f'<rect x="{pos(c["value"]) - 4:.1f}" y="8" width="8" height="8" class="p0-fp-pt"/></svg>')

    def svg_md(c):
        span = max(abs(c['ci_low']), abs(c['ci_high'])) * 1.15 or 1
        pos = lambda v: X0 + (v + span) / (2 * span) * (X1 - X0)
        return (f'<svg class="p0-fp" viewBox="0 0 {W} 24" role="img" aria-label="{ci_label(_("MD"), c)}">'
                f'<line x1="{pos(0):.1f}" y1="0" x2="{pos(0):.1f}" y2="24" class="p0-fp-null"/>'
                f'<line x1="{pos(c["ci_low"]):.1f}" y1="12" x2="{pos(c["ci_high"]):.1f}" y2="12" class="p0-fp-ci"/>'
                f'<rect x="{pos(c["value"]) - 4:.1f}" y="8" width="8" height="8" class="p0-fp-pt"/></svg>')

    def num(v, d=2):
        return fmt_number(v, d)

    arm = lambda g: _('{mean} (SD {sd}, n {n})', mean=g.get('mean'), sd=g.get('sd'), n=g.get('n'))
    blocks = []
    for oid in [o['id'] for o in review['outcomes']]:
        rows = [e for e in items if e['outcome'] == oid]
        if not rows:
            continue
        rows.sort(key=lambda e: (e['computed']['measure'], e.get('measure_label', ''), e.get('timepoint_months') or 0))
        trs = []
        for e in rows:
            c, g = e['computed'], e['groups']
            s = labels.get(e['study'], {})
            if c['measure'] == 'RR':
                data = _('{intervention} versus {comparator}', intervention=f'{g[ki].get("events")}/{g[ki].get("n")}', comparator=f'{g[kc].get("events")}/{g[kc].get("n")}')
                plot = svg_rr(c)
            else:
                data = _('{intervention} versus {comparator}', intervention=arm(g[ki]), comparator=arm(g[kc]))
                plot = svg_md(c)
            better = {True: _('higher value = better'), False: _('lower value = better')}.get(e.get('higher_is_better'), '')
            warn = f'<small class="p0-fp-warn">⚠ {escape(c["warning"])}</small>' if c.get('warning') else ''
            trs.append(f'''<tr><th scope="row"><a href="#{s.get('page_reference', '')}">{escape(s.get('label', e['study']))}</a><small>{escape(e.get('measure_label', ''))} · {escape(str(e.get('timepoint', '')))}</small></th>
                <td>{escape(data)}<small>{escape(e.get('access', ''))}{' · ' + better if better else ''}</small></td><td class="p0-fp-cell">{plot}</td>
                <td class="p0-fp-num"><strong>{_('MD') if c['measure'] == 'MD' else c['measure']} {num(c['value'])}</strong><small>{_('[{low}, {high}]', low=num(c['ci_low']), high=num(c['ci_high']))}</small>{warn}</td></tr>''')
        blocks.append(f'''<div class="study-context"><div class="table-scroll" role="region" tabindex="0" aria-label="{_('Effects by study, {outcome}', outcome=oid)}"><table class="p0-table p0-forest">
            <caption>{escape(oid)} · {escape(outcome_label.get(oid, ''))}</caption><thead><tr><th scope="col">{_('Study, measure, time point')}</th><th scope="col">{_('{intervention} versus {comparator}', intervention=escape(arms['intervention']['label']), comparator=escape(arms['comparator']['label']))}</th>
            <th scope="col">{_('Effect (point estimate, 95% CI)')}</th><th scope="col">{_('Value')}</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div></div>''')
    n_all = len(est.get('items', []))
    narrative = sum(1 for e in est['items'] if e.get('type') == 'narrative')
    return f'''<div class="p0-block" id="effets"><h3>{_('Effects by study, not pooled')}</h3>
        <p class="p0-lead">{_('No pooled effect calculated: each row is a trial, no overall effect is calculated. RR = relative risk ({intervention} / {comparator}, logarithmic scale from 0.05 to 20, vertical line = 1); MD = mean difference ({intervention} − {comparator}), scale specific to each row because the units differ, vertical line = 0.', intervention=escape(arms['intervention']['short']), comparator=escape(arms['comparator']['short']))}</p>
        {"".join(blocks)}
        <p class="table-note">{_('{n} computable effects out of {total} results extracted from the randomized trials ({narrative} results only described in words, without usable numbers; the others lack sample sizes or standard deviations by arm). Extraction: reviewer A on all outcomes, reviewer B on the critical outcomes, adjudication; each number is checked against a word-for-word quotation of the source. Sample sizes are those reported for the analysis, otherwise those randomized.', n=len(items), total=n_all, narrative=narrative)}</p></div>'''


def cohort_note(review):
    """Pairs of possibly overlapping studies (scripts/cohort_overlap.py) and their resolution."""
    c = review.get('cohorts', {})
    title = _('Cohort overlap')
    if c.get('status') == 'not_assessed':
        return f'<div class="p0-block" id="cohortes"><h3>{title}</h3><p class="p0-lead">{_("Not assessed for this review.")}</p></div>'
    labels = {'distinct': _('distinct cohorts'), 'overlap': _('overlap'), 'uncertain': _('uncertain')}
    rows = ''.join(f'''<tr><th scope="row">{escape(' / '.join(i['labels']))}</th><td>{escape(', '.join(i['shared_authors'][:5]))}</td>
        <td>{escape(labels.get((i.get('resolution') or {}).get('decision'), _('to be decided')))}</td><td>{escape((i.get('resolution') or {}).get('evidence', ''))}</td></tr>''' for i in c.get('items', []))
    table = (f'<div class="study-context"><div class="table-scroll" role="region" tabindex="0" aria-label="{_("Cohorts")}"><table class="p0-table"><caption>{_("Candidate pairs")}</caption>'
             f'<thead><tr><th scope="col">{_("Studies")}</th><th scope="col">{_("Shared authors")}</th><th scope="col">{_("Decision")}</th><th scope="col">{_("Evidence")}</th></tr></thead><tbody>{rows}</tbody></table></div></div>') if rows else ''
    return f'''<div class="p0-block" id="cohortes"><h3>{title}</h3><p class="p0-lead">{_('{note}. Detected by script (shared authors, registries, sample sizes, years), resolved by an agent on the archived sources.', note=escape(c.get('note', '')))}</p>{table}</div>'''
