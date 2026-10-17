"""Transcreve áudio ou vídeo local com faster-whisper, de graça e na própria máquina.

Aceita qualquer coisa que o ffmpeg abre: .ogg e .opus do WhatsApp, .mp3, .m4a, .wav, .mp4, .mov...
Para cada arquivo grava, na pasta de saída:
  <nome>.md   transcrição com minutagem [mm:ss] a cada trecho
  <nome>.srt  legenda pronta para editor de vídeo

Uso:
  python transcrever.py audio.ogg
  python transcrever.py *.ogg --idioma pt --modelo turbo --saida transcricoes

Precisa de: ffmpeg no PATH e `python -m pip install -U faster-whisper \"av<19\"`.

Desenvolvido por Guilherme Carlos da Silva
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def mmss(seg: float) -> str:
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def srt_tempo(seg: float) -> str:
    ms = int(round(seg * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def para_wav(origem: Path, destino: Path) -> None:
    """Converte para wav 16 kHz mono, o formato que o Whisper espera."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(origem), "-vn", "-ac", "1", "-ar", "16000", str(destino)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not destino.exists():
        raise RuntimeError(f"ffmpeg não conseguiu ler o áudio de {origem.name}: {r.stderr.strip()[-300:]}")


def carregar_modelo(nome: str):
    from faster_whisper import WhisperModel  # import aqui para o --help funcionar sem a biblioteca
    return WhisperModel(nome, device="cpu", compute_type="int8")


def transcrever(modelo, arquivo: Path, idioma: str | None) -> tuple[list[tuple[float, float, str]], str, float]:
    """Devolve (trechos, idioma detectado, duração em segundos)."""
    with tempfile.TemporaryDirectory(prefix="transcrever_") as tmp:
        wav = Path(tmp) / "audio.wav"
        para_wav(arquivo, wav)
        segmentos, info = modelo.transcribe(str(wav), language=idioma, vad_filter=True, beam_size=5)
        trechos = [(s.start, s.end, s.text.strip()) for s in segmentos if s.text.strip()]
    return trechos, info.language, info.duration


def gravar(arquivo: Path, pasta: Path, nome: str, trechos, idioma: str, duracao: float, modelo: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    md = pasta / f"{nome}.md"
    linhas = [
        f"# {arquivo.name}",
        "",
        f"- Duração: {mmss(duracao)} · Idioma: {idioma} · Modelo: {modelo}",
        f"- Transcrito em {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "Transcrição automática: nome próprio, número e sigla podem sair errados. Confira antes de citar.",
        "",
    ]
    linhas += [f"[{mmss(ini)}] {texto}" for ini, _, texto in trechos]
    linhas += ["", "---", "Skill transcrever-audio · Desenvolvido por Guilherme Carlos da Silva"]
    md.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    srt = pasta / f"{nome}.srt"
    blocos = [f"{i}\n{srt_tempo(ini)} --> {srt_tempo(fim)}\n{texto}\n" for i, (ini, fim, texto) in enumerate(trechos, 1)]
    srt.write_text("\n".join(blocos), encoding="utf-8")
    return md


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("arquivos", nargs="+", help="um ou mais arquivos de áudio ou vídeo")
    p.add_argument("--idioma", default=None, help="código do idioma (pt, en, es). Sem ele, o Whisper detecta sozinho")
    p.add_argument("--modelo", default="small",
                   help="small (rápido, padrão), turbo (melhor e ainda razoável no CPU) ou large-v3 (o melhor, lento)")
    p.add_argument("--saida", default=None, help="pasta de saída. Padrão: a mesma pasta de cada arquivo")
    a = p.parse_args()

    if not shutil.which("ffmpeg"):
        print("ffmpeg não encontrado no PATH. Instale com: winget install Gyan.FFmpeg", file=sys.stderr)
        return 1
    existentes = [n for n in a.arquivos if Path(n).exists()]
    if not existentes:
        print(json.dumps([{"arquivo": n, "ok": False, "erro": "arquivo não existe"} for n in a.arquivos],
                         ensure_ascii=False, indent=2))
        return 2
    try:
        modelo = carregar_modelo(a.modelo)
    except ImportError:
        print("faster-whisper não instalado. Rode: python -m pip install -U faster-whisper \"av<19\"", file=sys.stderr)
        return 1

    relatorio = []
    usados: set[tuple[str, str]] = set()  # (pasta, nome) já gravados nesta rodada
    for nome in a.arquivos:
        arq = Path(nome)
        if not arq.exists():
            relatorio.append({"arquivo": nome, "ok": False, "erro": "arquivo não existe"})
            continue
        try:
            trechos, idioma, duracao = transcrever(modelo, arq, a.idioma)
        except Exception as e:
            erro = str(e)[-300:]
            if "metadata_errors" in erro:
                erro += ". A versão 19 do PyAV quebra o faster-whisper. Rode: python -m pip install -U faster-whisper \"av<19\""
            relatorio.append({"arquivo": nome, "ok": False, "erro": erro})
            continue
        if not trechos:
            relatorio.append({"arquivo": nome, "ok": False, "erro": "nenhuma fala encontrada no áudio"})
            continue
        pasta = Path(a.saida) if a.saida else arq.parent
        base = arq.stem
        if (str(pasta), base) in usados:  # mesmo nome com extensão diferente: não sobrescrever
            base = f"{arq.stem}_{arq.suffix.lstrip('.')}"
        usados.add((str(pasta), base))
        md = gravar(arq, pasta, base, trechos, idioma, duracao, a.modelo)
        relatorio.append({"arquivo": nome, "ok": True, "transcricao": str(md), "idioma": idioma,
                          "palavras": sum(len(t.split()) for _, _, t in trechos)})
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    return 0 if any(r["ok"] for r in relatorio) else 2


if __name__ == "__main__":
    sys.exit(main())
