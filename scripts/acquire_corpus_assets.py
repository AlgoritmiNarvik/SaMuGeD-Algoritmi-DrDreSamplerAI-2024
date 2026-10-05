"""Acquire the pinned MIDI-only MAESTRO and PDMX expansion assets."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from samuged.acquire import download,extract_archive
assets=[('maestro-midi.zip','https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0-midi.zip','sha256:70470ee253295c8d2c71e6d9d4a815189e35c89624b76d22fce5a019d5dde12c',60*1024**2),('pdmx.csv','https://zenodo.org/api/records/15571083/files/PDMX.csv/content','md5:30392ccf38bb63ce70e7afae70f9c88c',230*1024**2),('pdmx-midi.tar.gz','https://zenodo.org/api/records/15571083/files/mid.tar.gz/content','md5:d920a21b2fcd99a56d9c381b39debbb2',220*1024**2)]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--download',action='store_true',help='download the explicitly listed assets')
    args=parser.parse_args()
    if not args.download:
        print(json.dumps([{'filename':n,'url':u,'checksum':c,'max_bytes':b} for n,u,c,b in assets],indent=2))
        return
    root=args.root;root.mkdir(parents=True,exist_ok=True)
    def work(asset):
        name,url,checksum,budget=asset
        receipt=download(url,root/name,checksum=checksum,max_bytes=budget,reserve_bytes=10*1024**3)
        print(name,receipt['bytes'],flush=True)
        return name,receipt
    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts=dict(pool.map(work,assets))
    (root/'acquisition.json').write_text(json.dumps(receipts,indent=2)+'\n')
    print('maestro extraction',extract_archive(root/'maestro-midi.zip',root/'maestro',max_bytes=120*1024**2,max_files=2000),flush=True)

if __name__=='__main__':main()
