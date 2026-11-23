#!/usr/bin/env python3
"""Second retrieval round for records judged "not retrieved" or assessed without text (protocol deviation 3).

  python3 -m emet.retrieval_round2 <subject>

Sources, cache-first under screening/eligibility/raw/: abstracts already archived in consensus.txt (Consensus
records), Crossref abstracts by DOI, the whole JATS article when PMC has no <body> (posters, abstracts),
ClinicalTrials.gov posted results. Writes screening/round2.json: ids whose available text changed.
"""
import json
from pathlib import Path
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

from emet.fulltext_stage import fetch  # noqa: E402
from emet.screening import folder, load, resolved, save  # noqa: E402

# The eligibility files (screening/eligibility/<id>.txt, written by fulltext_stage) have French field labels
# (RÉSUMÉ, ACCÈS, TEXTE INTÉGRAL…) and French access levels: the texts and regexes below match that archived
# format, and the registry summary is appended to it in the same language.


def consensus_abstracts(path):
    text = path.read_text() if path.exists() else ''
    blocks = re.split(r'\n(?=\[\d+\] \[)', text)
    out = {}
    for block in blocks:
        ident = re.search(r'\n\s+id: (w:[0-9a-f-]+)', block)
        if ident:
            body = block.split(ident.group(0), 1)[1].strip()
            out['CONS:' + ident.group(1)] = re.sub(r'\s+', ' ', body)
    return out


def crossref_abstract(doi, raw):
    path = raw/f'crossref-{re.sub(r"[^A-Za-z0-9]", "_", doi)}.json'
    if not path.exists():
        save(path, fetch('https://api.crossref.org/works/' + urllib.parse.quote(doi)) or {})
    message = load(path).get('message', {})
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', message.get('abstract', ''))).strip()


def ctgov_results(nct, raw):
    path = raw/f'{nct}.ctgov.json'
    if not path.exists():
        save(path, fetch(f'https://clinicaltrials.gov/api/v2/studies/{nct}') or {})
    study = load(path)
    results = study.get('resultsSection', {})
    lines = []
    for measure in results.get('outcomeMeasuresModule', {}).get('outcomeMeasures', []):
        groups = {g['id']: g.get('title', '') for g in measure.get('groups', [])}
        values = []
        for cls in measure.get('classes', []):
            for cat in cls.get('categories', []):
                for m in cat.get('measurements', []):
                    values.append(f"{groups.get(m.get('groupId'), m.get('groupId'))}{' ' + cls.get('title', '') if cls.get('title') else ''}{' ' + cat.get('title', '') if cat.get('title') else ''}: {m.get('value', '')}{' (' + m.get('spread', '') + ')' if m.get('spread') else ''}")
        lines.append(f"- {measure.get('type', '')} {measure.get('title', '')} [{measure.get('unitOfMeasure', '')}, {measure.get('timeFrame', '')}] : " + ' ; '.join(values))
    flow = results.get('participantFlowModule', {})
    status = study.get('protocolSection', {}).get('statusModule', {})
    design = study.get('protocolSection', {}).get('descriptionModule', {}).get('briefSummary', '')
    why = status.get('whyStopped', '')
    return (f"Statut : {status.get('overallStatus', '')}{' — arrêt : ' + why if why else ''}. Résumé du registre : {design}\n"
            f"Flux des participants : {json.dumps(flow.get('groups', []), ensure_ascii=False)[:1500]}\nRésultats déposés :\n" + '\n'.join(lines)) if results else ''


def main(subject):
    base = folder(subject)
    elig = base/'screening/eligibility'
    raw = elig/'raw'
    index = load(elig/'index.json')
    final = load(base/'screening/final.json')
    cons = consensus_abstracts(base/'consensus.txt')
    changed = {}
    for i, item in index.items():
        path = elig/item['file']
        text = path.read_text()
        has_abstract = bool(re.search(r'RÉSUMÉ:\n\S', text))
        added, access = '', None
        if i.startswith('CONS:') and not has_abstract and cons.get(i):
            added, access = cons[i], 'résumé (Consensus)'
        elif i in final['not_retrieved'] and item.get('doi'):
            abstract = crossref_abstract(item['doi'], raw)
            if abstract:
                added, access = abstract, 'résumé (Crossref)'
        elif i.startswith('NCT'):
            results = ctgov_results(i, raw)
            if results:
                added, access = results, 'registre avec résultats déposés'
        elif item['access'] == 'texte intégral' and not re.search(r'TEXTE INTÉGRAL:\n\S', text) and item.get('pmcid'):
            xml = (raw/f'{item["pmcid"]}.xml').read_text()
            body = re.sub(r'\s+', ' ', ' '.join(ET.fromstring(xml).itertext()))
            added, access = body, 'texte intégral (notice JATS sans corps : texte complet du document)'
        if added:
            text = re.sub(r'ACCÈS: .*', f'ACCÈS: {access}', text, count=1)
            text = text.replace('RÉSUMÉ:\n', f'RÉSUMÉ:\n{added}\n', 1) if not i.startswith('NCT') and 'JATS' not in access else text + f'\n\nCOMPLÉMENT (2e tour de récupération) :\n{added}\n'
            path.write_text(text)
            index[i]['access'] = access.split(' (')[0] if 'JATS' not in access else 'texte intégral'
            index[i]['round2'] = access
            changed[i] = access
    save(elig/'index.json', index)
    # Consensus records excluded at the abstract stage without any abstract: reassess with the archived abstract.
    abstracts = load(base/'screening/abstracts.json')
    decisions = resolved(base, 'abstracts')
    reassess = {i: cons[i] for i in abstracts if i.startswith('CONS:') and not abstracts[i]['abstract'] and cons.get(i) and decisions[i]['decision'] == 'exclude'}
    save(base/'screening/round2.json', {'eligibility_changed': changed, 'abstract_stage_reassess': reassess})
    print(subject, 'eligibility:', len(changed), 'records completed;', 'abstracts to reassess:', len(reassess))


if __name__ == '__main__':
    main(sys.argv[1])
