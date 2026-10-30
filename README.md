# MPPT Lab

MPPT制御をインタラクティブに学ぶためのシミュレーションソフトウェアです。

制御方式、ゲイン、回路のパラメータを変更し、電圧の応答や日射量が変わったときのMPPへの追従をグラフで確認できます。P&OとIncCond、Dutyの直接操作、電圧・電流のPI/PID制御を比較できます。

## 起動

Windows x64、Python 3.11を使用します。

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python server.py
```

ブラウザで http://127.0.0.1:8925/ を開いてください。

## 使い方

左側で回路・制御方式・実験条件を設定し、右側で電圧、電流、電力、測定タイミングを確認します。パラメータを選ぶと、説明や回路図でその役割を確認できます。

「ゲイン・制限」では、速度重視・バランス・行き過ぎ抑制の自動調整を試せます。

実機を操作する機能はありません。
