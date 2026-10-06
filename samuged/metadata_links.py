"""Bounded MusicBrainz core metadata candidates, never automatic song identification."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import time
import urllib.parse
import urllib.request

from .catalog_metadata import normalized

USER_AGENT='SaMuGeD/0.2 (https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSampler-2024)'


def candidates(path: Path, *, limit=20):
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('request limit must be 1 to 100')
    db=sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro',uri=True)
    rows=db.execute('SELECT source_key,artist,title FROM records WHERE dataset_id=? AND artist IS NOT NULL AND title IS NOT NULL ORDER BY source_key LIMIT ?',('lakh',limit)).fetchall();db.close()
    output=[];failures=[]
    for index,(key,artist,title) in enumerate(rows):
        if index:time.sleep(1.1)
        def clean(v):return re.sub(r'[^\w\s]',' ',v.replace('_',' ')).strip()[:250]
        query=f'recording:"{clean(title)}" AND artist:"{clean(artist)}"'
        url='https://musicbrainz.org/ws/2/recording/?'+urllib.parse.urlencode(dict(query=query,fmt='json',limit=5))
        try:
            req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
            with urllib.request.urlopen(req,timeout=15) as response:
                payload=response.read(1024*1024+1)
                if len(payload)>1024*1024:raise ValueError('response too large')
                data=json.loads(payload)
            for record in data.get('recordings',[])[:5]:
                credit=''.join(x.get('name',x.get('artist',{}).get('name',''))+x.get('joinphrase','') for x in record.get('artist-credit',[]) if isinstance(x,dict))
                # Even agreement of normalized labels is only a candidate, not an audio/MIDI match.
                if normalized(clean(record.get('title','')))!=normalized(clean(title)) or normalized(clean(credit))!=normalized(clean(artist)):continue
                entity=record['id']
                output.append(dict(source_key=key,provider='musicbrainz',entity_id=entity,title=record['title'],artist=credit,
                    evidence_url='https://musicbrainz.org/recording/'+entity,metadata_license='CC0-1.0',
                    match_status='candidate',method='normalized_title_artist_agreement',retrieved_on=datetime.now(timezone.utc).date().isoformat()))
        except Exception as exc:
            failures.append(dict(source_key=key,error=type(exc).__name__))
            # Stop on service failures rather than multiplying retries or issuing a burst.
            break
    return dict(requested_limit=limit,source_queries=index+1 if rows else 0,candidates=output,failures=failures,
                metadata_scope='recording ID, title and artist credit only; no tags, ratings, descriptions or lyrics')
