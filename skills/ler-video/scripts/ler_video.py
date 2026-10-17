"""Baixa um vídeo por link (Instagram, YouTube, TikTok...) ou abre um arquivo local e prepara tudo para estudar.

Grava numa pasta própria:
  midia/            o vídeo (ou as fotos de um carrossel) baixado
  quadros/          um quadro em resolução cheia a cada N segundos, com a minutagem no nome
  cortes/           um quadro em resolução cheia a cada troca de cena
  folha_NN.jpg      folhas de contato (miniaturas em grade) para ver o vídeo inteiro de relance
  transcricao.md    a fala, com minutagem [mm:ss]
  RELATORIO.md      link, autor, data, legenda do post, duração e onde está cada coisa

Uso:
  python ler_video.py "https://www.instagram.com/reel/XXXX/"
  python ler_video.py "https://youtu.be/XXXX" --intervalo 5 --modelo turbo
  python ler_video.py "C:/Users/<voce>/Downloads/video.mp4"

Instagram pede login. O script procura o cookie em ~/.secrets/instagram-cookies.txt
ou no caminho passado em --cookies. Esse arquivo vale a senha da conta: nunca compartilhe.

Precisa de: ffmpeg, yt-dlp, faster-whisper (com "av<19"); gallery-dl para carrossel de fotos do Instagram.

Desenvolvido por Guilherme Carlos da Silva
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

COOKIE_PADRAO = Path.home() / ".secrets" / "instagram-cookies.txt"
CREDITO = "Desenvolvido por Guilherme Carlos da Silva"
VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def rodar(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def mmss(seg: float) -> str:
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def slug(texto: str) -> str:
    texto = re.sub(r"[^A-Za-z0-9_-]+", "-", texto).strip("-")
    return texto[-60:] or "video"


def nome_da_pasta(origem: str) -> str:
    """Usa o código do post/vídeo quando dá, para a pasta ter nome reconhecível."""
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:reel|reels|p|tv)/([^/?#]+)", origem)
    if m:
        return "instagram-" + m.group(1)
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", origem)
    if m:
        return "youtube-" + m.group(1)
    m = re.search(r"tiktok\.com/.*/video/(\d+)", origem)
    if m:
        return "tiktok-" + m.group(1)
    return slug(Path(origem).stem if Path(origem).exists() else origem)


# ---------------------------------------------------------------- baixar

def baixar_ytdlp(url: str, destino: Path, cookies: Path | None) -> tuple[bool, str]:
    cmd = ["yt-dlp", "--no-playlist", "--write-info-json", "-f", "bv*+ba/b", "--merge-output-format", "mp4",
           "-o", str(destino / "%(id)s.%(ext)s")]
    if shutil.which("node"):
        cmd[1:1] = ["--js-runtimes", "node"]  # o YouTube hoje exige um runtime de JavaScript
    if cookies:
        cmd += ["--cookies", str(cookies)]
    r = rodar(cmd + [url])
    return r.returncode == 0, r.stderr.strip()[-500:]


def baixar_gallerydl(url: str, destino: Path, cookies: Path | None) -> tuple[bool, str]:
    """Plano B para o Instagram: pega carrossel de fotos e posts que o yt-dlp não abre."""
    if not shutil.which("gallery-dl"):
        return False, "gallery-dl não instalado (python -m pip install gallery-dl)"
    cmd = ["gallery-dl", "--write-metadata", "-D", str(destino), "-f", "{num:>02}.{extension}"]
    if cookies:
        cmd += ["--cookies", str(cookies)]
    r = rodar(cmd + [url])
    return r.returncode == 0, r.stderr.strip()[-500:]


def metadados(pasta: Path) -> dict:
    """Junta o que o yt-dlp ou o gallery-dl gravaram sobre o post."""
    for arq in sorted(pasta.glob("*.info.json")) + sorted(pasta.glob("*.json")):
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data = d.get("upload_date") or str(d.get("date") or d.get("post_date") or "")
        if re.fullmatch(r"\d{8}", data):
            data = f"{data[:4]}-{data[4:6]}-{data[6:]}"
        return {
            "titulo": d.get("title") or d.get("fulltitle"),
            "autor": d.get("uploader") or d.get("channel") or d.get("username") or d.get("owner_id"),
            "data": data[:10] or None,
            "legenda": d.get("description") or d.get("caption"),
            "views": d.get("view_count"),
            "curtidas": d.get("like_count") or d.get("likes"),
            "comentarios": d.get("comment_count"),
            "link": d.get("webpage_url") or d.get("post_url"),
        }
    return {}


# ---------------------------------------------------------------- estudar o vídeo

def duracao(video: Path) -> float:
    r = rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)])
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return 0.0


def tem_audio(video: Path) -> bool:
    r = rodar(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(video)])
    return bool(r.stdout.strip())


def resolucao(video: Path) -> str:
    r = rodar(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
               "-of", "csv=s=x:p=0", str(video)])
    return r.stdout.strip() or "n/d"


def limpar(pasta: Path, *padroes: str) -> None:
    """Apaga o que uma rodada anterior deixou, para poder rodar de novo no mesmo vídeo."""
    for padrao in padroes:
        for arq in pasta.glob(padrao):
            arq.unlink(missing_ok=True)


def selecao_por_tempo(intervalo: float) -> str:
    """Pega o primeiro quadro e depois um a cada `intervalo` segundos, no tempo real do vídeo."""
    return f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{intervalo})'"


def extrair_quadros(video: Path, pasta: Path, intervalo: float) -> int:
    """Um quadro em resolução cheia a cada `intervalo` segundos, nomeado pela minutagem real."""
    pasta.mkdir(parents=True, exist_ok=True)
    limpar(pasta, "tmp_*.jpg", "q_*.jpg")
    r = rodar(["ffmpeg", "-y", "-i", str(video), "-vf", selecao_por_tempo(intervalo) + ",showinfo",
               "-fps_mode", "vfr", "-q:v", "2", str(pasta / "tmp_%05d.jpg")])
    tempos = [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    feitos = sorted(pasta.glob("tmp_*.jpg"))
    for i, arq in enumerate(feitos):
        t = tempos[i] if i < len(tempos) else i * intervalo
        arq.replace(pasta / f"q_{i + 1:03d}_{mmss(t).replace(':', '-')}.jpg")
    return len(feitos)


def extrair_cortes(video: Path, pasta: Path, limiar: float) -> int:
    """Um quadro em resolução cheia em cada troca de cena (sempre inclui o primeiro)."""
    pasta.mkdir(parents=True, exist_ok=True)
    limpar(pasta, "tmp_*.jpg", "corte_*.jpg")
    filtro = f"select='eq(n\\,0)+gt(scene\\,{limiar})',showinfo"
    r = rodar(["ffmpeg", "-y", "-i", str(video), "-vf", filtro, "-fps_mode", "vfr", "-q:v", "2",
               str(pasta / "tmp_%05d.jpg")])
    tempos = [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    feitos = sorted(pasta.glob("tmp_*.jpg"))
    for i, arq in enumerate(feitos):
        t = tempos[i] if i < len(tempos) else 0
        arq.replace(pasta / f"corte_{i + 1:03d}_{mmss(t).replace(':', '-')}.jpg")
    return len(feitos)


def folhas_de_contato(video: Path, pasta: Path, intervalo: float, dur: float) -> int:
    """Miniaturas em grade 6x5, na mesma ordem da pasta quadros/; vídeo longo vira várias folhas."""
    limpar(pasta, "folha_*.jpg")
    por_folha = 30
    total = max(1, math.floor(dur / intervalo) + 1) if dur else por_folha
    colunas = min(6, total)
    linhas = min(5, math.ceil(min(total, por_folha) / colunas))
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf",
           selecao_por_tempo(intervalo) + f",scale=320:-2,tile={colunas}x{linhas}:padding=4:margin=4",
           "-fps_mode", "vfr", "-q:v", "3", str(pasta / "folha_%02d.jpg")])
    return len(list(pasta.glob("folha_*.jpg")))


def transcrever(video: Path, modelo_nome: str, idioma: str | None) -> tuple[list[tuple[float, str]], str]:
    from faster_whisper import WhisperModel
    with tempfile.TemporaryDirectory(prefix="ler_video_") as tmp:
        wav = Path(tmp) / "audio.wav"
        r = rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg não extraiu o áudio: {r.stderr.strip()[-300:]}")
        modelo = WhisperModel(modelo_nome, device="cpu", compute_type="int8")
        segmentos, info = modelo.transcribe(str(wav), language=idioma, vad_filter=True, beam_size=5)
        trechos = [(s.start, s.text.strip()) for s in segmentos if s.text.strip()]
    return trechos, info.language


# ---------------------------------------------------------------- main

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("origem", help="link do vídeo ou caminho de um arquivo local")
    p.add_argument("--saida", default=str(Path.home() / "ler-video"),
                   help="pasta-mãe; cada vídeo ganha uma subpasta. Padrão: <pasta do usuário>/ler-video")
    p.add_argument("--cookies", default=None, help="cookies.txt (formato Netscape) para Instagram ou vídeo restrito")
    p.add_argument("--intervalo", type=float, default=2.0, help="segundos entre um quadro e outro (padrão 2)")
    p.add_argument("--limiar-corte", type=float, default=0.3, help="sensibilidade da troca de cena, 0 a 1 (padrão 0.3)")
    p.add_argument("--modelo", default="small", help="modelo do Whisper: small, turbo ou large-v3")
    p.add_argument("--idioma", default=None, help="idioma da fala (pt, en...). Sem ele, detecta sozinho")
    p.add_argument("--sem-transcricao", action="store_true")
    p.add_argument("--sem-quadros", action="store_true")
    a = p.parse_args()

    for prog in ("ffmpeg", "ffprobe"):
        if not shutil.which(prog):
            print(f"{prog} não encontrado. Instale com: winget install Gyan.FFmpeg", file=sys.stderr)
            return 1

    pasta = Path(a.saida) / nome_da_pasta(a.origem)
    midia = pasta / "midia"
    midia.mkdir(parents=True, exist_ok=True)
    rel = {"origem": a.origem, "pasta": str(pasta), "avisos": []}

    local = Path(a.origem)
    if local.exists():
        shutil.copy2(local, midia / local.name)
    else:
        cookies = Path(a.cookies) if a.cookies else None
        eh_instagram = "instagram.com" in a.origem
        if cookies is None and eh_instagram and COOKIE_PADRAO.exists():
            cookies = COOKIE_PADRAO
        if cookies is not None and not cookies.exists():
            print(f"Cookie não encontrado em {cookies}", file=sys.stderr)
            return 1
        if not shutil.which("yt-dlp"):
            print('yt-dlp não instalado. Rode: python -m pip install -U "yt-dlp[default,curl-cffi]"', file=sys.stderr)
            return 1
        ok, erro = baixar_ytdlp(a.origem, midia, cookies)
        if not ok and eh_instagram:
            rel["avisos"].append(f"yt-dlp falhou, tentando gallery-dl: {erro[-200:]}")
            ok, erro = baixar_gallerydl(a.origem, midia, cookies)
        if not ok:
            if not any(midia.iterdir()):
                shutil.rmtree(pasta, ignore_errors=True)
            dica = ""
            if re.search(r"impersonat", erro, re.I):
                dica = ' Falta um componente do yt-dlp: python -m pip install -U "yt-dlp[default,curl-cffi]"'
            elif eh_instagram and cookies is None:
                dica = " O Instagram pede login: exporte o cookies.txt (veja o README do repositório) e passe --cookies."
            elif re.search(r"login|cookie|rate.?limit|401|403", erro, re.I):
                dica = ' Atualize as ferramentas (python -m pip install -U "yt-dlp[default,curl-cffi]" gallery-dl) e, se continuar, renove o cookie.'
            print(f"Não consegui baixar: {erro}{dica}", file=sys.stderr)
            return 2

    rel["post"] = metadados(midia)
    videos = sorted(f for f in midia.iterdir() if f.suffix.lower() in VIDEO)
    imagens = sorted(f for f in midia.iterdir() if f.suffix.lower() in IMAGEM)
    rel["imagens"] = [str(f) for f in imagens]
    rel["videos"] = []

    for v in videos:
        info = {"arquivo": str(v), "duracao": mmss(duracao(v)), "resolucao": resolucao(v)}
        dur = duracao(v)
        sufixo = "" if len(videos) == 1 else f"_{v.stem}"
        if not a.sem_quadros:
            info["quadros"] = extrair_quadros(v, pasta / f"quadros{sufixo}", a.intervalo)
            info["cortes"] = extrair_cortes(v, pasta / f"cortes{sufixo}", a.limiar_corte)
            alvo = pasta if len(videos) == 1 else pasta / f"folhas{sufixo}"
            alvo.mkdir(exist_ok=True)
            info["folhas"] = folhas_de_contato(v, alvo, a.intervalo, dur)
        if not a.sem_transcricao:
            if not tem_audio(v):
                info["transcricao"] = "vídeo sem áudio"
            else:
                try:
                    trechos, idioma = transcrever(v, a.modelo, a.idioma)
                except ImportError:
                    rel["avisos"].append("faster-whisper não instalado: python -m pip install -U faster-whisper \"av<19\"")
                    info["transcricao"] = "falhou (ver Avisos)"
                    trechos, idioma = [], None
                except Exception as e:
                    erro = str(e)[-200:]
                    if "metadata_errors" in erro:
                        erro += ". A versão 19 do PyAV quebra o faster-whisper. Rode: python -m pip install -U faster-whisper \"av<19\""
                    rel["avisos"].append(f"transcrição falhou: {erro}")
                    info["transcricao"] = "falhou (ver Avisos)"
                    trechos, idioma = [], None
                if trechos:
                    arq = pasta / f"transcricao{sufixo}.md"
                    corpo = [f"# Transcrição de {v.name}", "",
                             f"Idioma: {idioma} · Modelo: {a.modelo} · Gerado em {datetime.now():%Y-%m-%d %H:%M}",
                             "Automática: nome próprio, número e sigla podem sair errados.", ""]
                    corpo_fim = ["", "---", f"Skill ler-video · {CREDITO}"]
                    corpo += [f"[{mmss(t)}] {texto}" for t, texto in trechos]
                    arq.write_text("\n".join(corpo + corpo_fim) + "\n", encoding="utf-8")
                    info["transcricao"] = str(arq)
                elif "transcricao" not in info:
                    info["transcricao"] = "sem fala detectada"
        rel["videos"].append(info)

    if not videos and not imagens:
        rel["avisos"].append("nada de vídeo ou imagem na pasta midia/")

    post = rel["post"]
    md = [f"# {post.get('titulo') or nome_da_pasta(a.origem)}", "",
          f"- Origem: {post.get('link') or a.origem}",
          f"- Autor: {post.get('autor') or 'n/d'} · Data: {post.get('data') or 'n/d'}",
          f"- Views: {post.get('views') or 'n/d'} · Curtidas: {post.get('curtidas') or 'n/d'} · Comentários: {post.get('comentarios') or 'n/d'}",
          ""]
    if post.get("legenda"):
        md += ["## Legenda do post", "", post["legenda"].strip(), ""]
    for info in rel["videos"]:
        md += [f"## {Path(info['arquivo']).name}", "",
               f"- Duração {info['duracao']} · Resolução {info['resolucao']}",
               f"- Quadros a cada {a.intervalo:g}s: {info.get('quadros', 'não gerados')} · Trocas de cena: {info.get('cortes', 'n/d')} · Folhas de contato: {info.get('folhas', 'n/d')}",
               f"- Transcrição: {info.get('transcricao', 'não pedida')}", ""]
    if imagens:
        md += ["## Imagens", ""] + [f"- {Path(f).name}" for f in imagens] + [""]
    if rel["avisos"]:
        md += ["## Avisos", ""] + [f"- {x}" for x in rel["avisos"]] + [""]
    md += ["---", f"Skill ler-video · {CREDITO}", ""]
    (pasta / "RELATORIO.md").write_text("\n".join(md), encoding="utf-8")

    print(json.dumps(rel, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
