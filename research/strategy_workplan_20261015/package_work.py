"""Package explicit public research allowlists; no raw CoinGlass/WEEX or account data."""
from pathlib import Path
import hashlib
import json
import platform
import shutil
import zipfile

ROOT=Path(__file__).resolve().parent
RESEARCH=ROOT.parent
PUBLISH=RESEARCH/'weex_publish_20261010'
DOCS=PUBLISH/'docs'

def sha(data): return hashlib.sha256(data).hexdigest()

def add_file(items,p,arcname):
    if not p.is_file() or p.is_symlink(): raise ValueError('Missing/unsafe package input: '+str(p))
    if arcname in items: raise ValueError('duplicate member')
    items[arcname]=p.read_bytes()

def make_zip(path,items,description):
    if path.exists(): raise ValueError('Refusing to overwrite '+str(path))
    manifest={'description':description,'files':[{'name':k,'bytes':len(v),'sha256':sha(v)} for k,v in sorted(items.items())]}
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in sorted(items.items()):
            z.writestr(name,data)
        z.writestr('PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert sorted(z.namelist())==sorted([*items,'PACKAGE_MANIFEST.json'])
        for f in manifest['files']:
            assert sha(z.read(f['name']))==f['sha256']
    return {'file':path.name,'bytes':path.stat().st_size,'sha256':sha(path.read_bytes()),'members':len(items)+1}

def main():
    # Exactly these new research folders; only one-level reviewed files, never recursive state.
    selections={
      'cg_sr1_20261015':['cg_sr1.py','test_cg_sr1.py','make_synthetic_fixture.py','README.md','VALIDATION.md','synthetic_example_report.json'],
      'public_market_export_20261015':['export_public_market.py','test_export_public_market.py','README.md'],
      'strategy_workplan_20261015':['fetch_spot_flow_history.py','test_spot_flow_history.py','README.md','package_work.py'],
    }
    items={}
    for folder,names in selections.items():
        for name in names:
            source=RESEARCH/folder/name
            add_file(items,source,'research/'+folder+'/'+name)
            # Source is reviewable directly in GitHub in addition to the frozen ZIP bytes.
            dest=PUBLISH/'research'/folder/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists(): raise ValueError('Unexpected existing publication file: '+str(dest))
            shutil.copyfile(source,dest)
    eth=RESEARCH/'eth_causal_replay_20261015'
    # Finite result directory: exact suffixes, one level, no temporary folders.
    eth_names=[p.name for p in eth.iterdir() if p.is_file() and p.suffix in {'.py','.md','.json','.csv'}]
    assert 'ROOT_INDEPENDENT_QA.json' in eth_names and 'REPORT.json' in eth_names
    for name in sorted(eth_names): add_file(items,eth/name,'research/eth_causal_replay_20261015/'+name)
    # ETH reproducer verifies these exact seven public inputs before computation.
    eth_manifest=json.loads((eth/'INPUT_MANIFEST.json').read_bytes())
    for f in eth_manifest['files']:
        rel=Path(f['file'])
        if rel.is_absolute() or '..' in rel.parts: raise ValueError('unsafe manifest member')
        p=RESEARCH/rel
        assert sha(p.read_bytes())==f['sha256']
        add_file(items,p,'research/'+rel.as_posix())
    add_file(items,RESEARCH/'expectancy_20261006/public_data/binance_futures_BTCUSDT_1m.csv',
             'research/expectancy_20261006/public_data/binance_futures_BTCUSDT_1m.csv')
    history=ROOT/'public_history'
    for name in ('binance_spot_BTCUSDT_15m.csv','paired_BTCUSDT_spot_perp_15m.csv','manifest.json'):
        add_file(items,history/name,'research/strategy_workplan_20261015/public_history/'+name)
    for date in ('2026-05','2026-06','2026-07','2026-08','2026-09',
                 '2026-10-01','2026-10-02','2026-10-03','2026-10-04','2026-10-05'):
        for suffix in ('.zip','.zip.CHECKSUM'):
            name='BTCUSDT-15m-'+date+suffix
            add_file(items,history/'archive_cache'/name,
                     'research/strategy_workplan_20261015/public_history/archive_cache/'+name)
    for name in ('TRADING_SYSTEM_WORKPLAN_2026-10-15.md','ETH_CAUSAL_REPLAY_2026-10-15.md',
                 'HEATMAP_NEXT_TESTS_2026-10-15.md','COINGLASS_DATA_PRIORITY_2026-10-15.md'):
        add_file(items,DOCS/name,'docs/'+name)
    items['README_REPRO.md']=(
      '# Research reproducibility package, 15 October 2026\n\n'
      'Public Binance inputs, historical simulations and explicitly synthetic CG/helper fixtures only. '
      'No raw CoinGlass screenshots/journal, WEEX recordings, private fills, credentials or account state. '
      'No live collector, bot deployment or Claude/Anthropic calls.\n\n'
      'Extract to a NEW directory preserving research/ paths. Inspect docs/TRADING_SYSTEM_WORKPLAN_2026-10-15.md. '
      'ETH requires Python with numpy/pandas; CG, exporter and historical loader use the standard library.\n\n'
      'From research/eth_causal_replay_20261015: python -m unittest -v test_replay; python run_replay.py; '
      'python root_independent_qa.py. The replay replaces only its own local result files.\n\n'
      'From research/cg_sr1_20261015: python -m unittest -v test_cg_sr1. '
      'make_synthetic_fixture.py creates only clearly labeled fictional inputs; see README.\n\n'
      'From research/strategy_workplan_20261015: python -m unittest -v test_spot_flow_history; '
      'python fetch_spot_flow_history.py (included cache makes this offline).\n\n'
      'From research/public_market_export_20261015: python -m unittest -v test_export_public_market. '
      'Do not use the exporter on an account directory; its explicit whitelist expects recorder public CSV. '
      'Native Mac run is unverified. This helper exports existing files and is NOT a recorder.\n\n'
      'Windows sandbox TMP failures: choose a writable task-local temporary directory for the test process; '
      'this does not alter algorithm/data. One symlink test may skip when OS forbids creating symlinks.\n\n'
      'Every member except this manifest is hashed in PACKAGE_MANIFEST.json. '
      'Numerical correctness, synthetic PASS and inspected historical gains are not evidence of out-of-sample profit.\n'
    ).encode('utf-8')
    assert all(not n.startswith(('/', '\\')) and '..' not in Path(n).parts for n in items)
    assert not any(n.lower().endswith(('.sqlite','.db','.png','.jpg','.jpeg','.env','.jsonl')) for n in items)
    helper={name:(RESEARCH/'public_market_export_20261015'/name).read_bytes()
            for name in selections['public_market_export_20261015']}
    helper_info=make_zip(DOCS/'PUBLIC_MARKET_EXPORT_HELPER_2026-10-15.zip',helper,
                        'Offline public-market whitelist exporter; no real data; not run on Mac')
    main_info=make_zip(DOCS/'STRATEGY_WORK_REPRO_2026-10-15.zip',items,
                      'Public history and offline research; previously inspected data, no trading validation')
    report={'status':'PASS','archives':[helper_info,main_info],'only_public_historical_or_synthetic':True,
            'raw_CoinGlass_or_WEEX_included':False,'private_account_included':False,
            'python':platform.python_version()}
    (ROOT/'PUBLICATION_PACKAGE_QA.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
