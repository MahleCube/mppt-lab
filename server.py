"""Local HTTP UI with Python circuit models and native c07 r03/r04 control cores."""
from __future__ import annotations
import argparse
import gzip
import json
import mimetypes
import re
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from engine import DEFAULTS, LIMITS, PRESETS, configuration, simulate, SimulationCancelled
from controllers import ALGORITHMS
from plant import PLANT_FIELDS
from parameter_sets import parameter_sets
from circuit_references import circuit_references
from autotune_jobs import TuningJobs
from autotune import capability as tuning_capability
from pv_operating_point import calculate_start_mpp

ROOT=Path(__file__).resolve().parent
STATIC=ROOT/"static"
C07_PRESET=json.loads((ROOT/"c07_preset.json").read_text(encoding="utf-8"))
C07_PRESET["config"]=configuration(C07_PRESET["config"])
EXPERIMENTS=[
    dict(id="voltage",label="電圧ステップ追従",description="日射量を一定にし、PV電圧目標の変化に追従させます。Libre SolarとFUGUには比較用の電圧追従処理を追加します。"),
    dict(id="irradiance",label="日射変化・MPP追従",description="指定時刻から日射量を変え、制御器が測定値からMPPを追従します。真のモデルMPPは評価にだけ使い、制御器へ渡しません。")]
APP_PRESETS=parameter_sets(C07_PRESET)
CIRCUIT_REFERENCES=circuit_references()
APP_DEFAULTS=dict(C07_PRESET['config'])
# Open the composable teaching controller without mixing its gains into a circuit set.
custom=next((a for a in ALGORITHMS if a['id']=='custom'),None)
if custom:
    circuit_keys=set().union(*(set(p['config']) for p in APP_PRESETS))
    APP_DEFAULTS.update({k:v for k,v in custom['preset'].items() if k not in circuit_keys})
DOCUMENT_ROUTES=frozenset((
    "/README.md","/MODEL.md","/ALGORITHMS.md","/AUTOTUNE.md",
    "/C07_R03.md","/C07_R04.md","/C07_MODEL_EXTENSION.md",
    "/c07_preset.json","/THIRD_PARTY_NOTICES.md"))
LOCK=threading.Lock()
CACHE=OrderedDict()
LATEST={}
REVISION_LOCK=threading.Lock()
TUNING=TuningJobs(LOCK)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        print(format % args,flush=True)

    def send_data(self,payload,status=200,content_type="application/json; charset=utf-8",timing=None):
        encoding_start=time.perf_counter()
        data=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode() if not isinstance(payload,bytes) else payload
        encode_ms=(time.perf_counter()-encoding_start)*1000
        compression_start=time.perf_counter()
        compressed="gzip" in self.headers.get("Accept-Encoding","") and len(data)>50000
        if compressed: data=gzip.compress(data,compresslevel=1)
        compress_ms=(time.perf_counter()-compression_start)*1000
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        if compressed: self.send_header("Content-Encoding","gzip")
        if timing is not None:
            values={**timing,'encode':encode_ms,'compress':compress_ms}
            self.send_header('Server-Timing',', '.join(f'{key};dur={value:.3f}' for key,value in values.items()))
        self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass

    def do_GET(self):
        path=unquote(urlsplit(self.path).path)
        tuning_match=re.fullmatch(r'/api/autotune/([a-f0-9]{32})',path)
        if tuning_match:
            job=TUNING.read(tuning_match.group(1))
            self.send_data(job if job else dict(error='自動調整の記録が見つかりません。'),200 if job else 404); return
        if path=="/api/health":
            self.send_data(dict(app="pv-pid-lab",engine="Python / Numba + SciPy reference / c07 native control core",version=3,features=['all-method-autotune-v2','c07-r04-autotune-v1','c07-r03-control-core','c07-r04-control-core','start-mpp-v1'])); return
        if path=="/api/config":
            verification=None
            report=ROOT/"verification-v3.json"
            if report.exists():
                verification=json.loads(report.read_text(encoding="utf-8"))
            self.send_data(dict(version=3,defaults=APP_DEFAULTS,presets=APP_PRESETS,limits=LIMITS,
                algorithms=ALGORITHMS,plant_fields=PLANT_FIELDS,experiments=EXPERIMENTS,circuit_references=CIRCUIT_REFERENCES,
                default_preset_id=C07_PRESET["id"],reference_preset=C07_PRESET,
                verification=verification,verification_url="/verification-v3.json" if verification else None)); return
        if path in DOCUMENT_ROUTES:
            target=ROOT/path.lstrip("/")
        else:
            target=(STATIC/("index.html" if path=="/" else path.lstrip("/"))).resolve()
            if not target.is_relative_to(STATIC.resolve()):
                self.send_data(dict(error="not found"),404); return
        if not target.is_file(): self.send_data(dict(error="not found"),404); return
        typ=mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in (".html",".js",".css",".md"): typ += "; charset=utf-8"
        self.send_data(target.read_bytes(),content_type=typ)

    def do_POST(self):
        path=urlsplit(self.path).path
        tuning_cancel=re.fullmatch(r'/api/autotune/([a-f0-9]{32})/cancel',path)
        if path not in ("/api/simulate","/api/cancel","/api/autotune","/api/autotune/capability","/api/start-mpp") and not tuning_cancel:
            self.send_data(dict(error="not found"),404); return
        try:
            length=int(self.headers.get("Content-Length",0))
            if not 0<length<=16000: raise ValueError("設定データのサイズが不正です。")
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError("設定はJSONオブジェクトで指定してください。")
            if path=="/api/autotune/capability":
                if not isinstance(data.get('config'),dict):
                    raise ValueError('自動調整の対象設定を指定してください。')
                config=configuration(data['config'])
                available=tuning_capability(config)
                keys=available.get('tunable_keys',available.get('gain_keys',[]))
                available={**available,'parameter_specs':{key:{'min':LIMITS[key][0],'max':LIMITS[key][1],**available.get('parameter_specs',{}).get(key,{})} for key in keys if key in LIMITS}}
                self.send_data(available); return
            if path=="/api/start-mpp":
                self.send_data(calculate_start_mpp(data)); return
            if tuning_cancel:
                job=TUNING.cancel(tuning_cancel.group(1))
                self.send_data(job if job else dict(error='自動調整の記録が見つかりません。'),200 if job else 404); return
            if path=="/api/autotune":
                if not isinstance(data.get('config'),dict):
                    raise ValueError('自動調整する回路と制御の設定を指定してください。')
                job=TUNING.create(configuration(data['config']),data.get('profile','balanced'))
                self.send_data(job,202); return
            client=self.headers.get("X-PV-Client","")[:128]
            revision=int(self.headers.get("X-PV-Revision","0"))
            if client:
                with REVISION_LOCK:
                    LATEST[client]=max(revision,LATEST.get(client,0))
            def cancelled():
                return bool(client and LATEST.get(client,revision)>revision)
            if path=="/api/cancel":
                self.send_data(dict(cancelled=True)); return
            config=configuration(data)
            key=json.dumps(config,sort_keys=True)
            # One compute job at a time; deterministic completed configurations
            # may be reused. This caches full results, not an averaged plant.
            queue_start=time.perf_counter()
            with LOCK:
                queue_ms=(time.perf_counter()-queue_start)*1000
                compute_start=time.perf_counter()
                if cancelled(): raise SimulationCancelled()
                if key in CACHE:
                    result=CACHE[key]
                    CACHE.move_to_end(key)
                    result={**result,"diagnostics":{**result["diagnostics"],"cache_hit":True}}
                else:
                    result=simulate(config,cancelled=cancelled)
                    # Detailed verification retains event logs in the engine;
                    # the UI uses the correlated per-sample timings instead.
                    result={k:v for k,v in result.items() if k!="events"}
                    result["diagnostics"]["cache_hit"]=False
                    if result["metrics"]["completed"]:
                        CACHE[key]=result
                        while len(CACHE)>5: CACHE.popitem(last=False)
                compute_ms=(time.perf_counter()-compute_start)*1000
            if cancelled(): raise SimulationCancelled()
            self.send_data(result,timing={'queue':queue_ms,'compute':compute_ms})
        except SimulationCancelled:
            self.send_data(dict(cancelled=True),409)
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            self.send_data(dict(error=str(exc)),400)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.send_data(dict(error="計算を完了できませんでした: "+str(exc)),500)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8925)
    args=parser.parse_args()
    from fast_integrator import warmup as legacy_warmup
    from plant import warmup as plant_warmup
    from waveform_summary import warmup as waveform_warmup
    from tuning_simulator import warmup as tuning_warmup
    print("Preparing compiled Python integrator...",flush=True)
    legacy_warmup()
    plant_warmup()
    waveform_warmup()
    tuning_warmup()
    server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    server.daemon_threads=True
    print(f"PV PID Lab http://127.0.0.1:{server.server_port}/",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
