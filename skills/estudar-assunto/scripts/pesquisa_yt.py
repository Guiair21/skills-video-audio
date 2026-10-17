"""Busca e transcrição de vídeos do YouTube para a skill estudar-assunto.

Três comandos:
  buscar       junta resultados de várias consultas, aplica o piso de views e de duração,
               enriquece os melhores com dados do canal e grava candidatos.json
  enriquecer   completa os dados do canal dos vídeos escolhidos que ficaram sem eles
  transcrever  baixa a legenda dos vídeos escolhidos e grava um .md por vídeo, com minutagem

Três fontes, escolhidas caso a caso com --fonte:
  ytdlp          grátis, sem chave (padrão). Pode ser bloqueado pelo YouTube por um tempo.
  transcriptapi  usa TRANSCRIPT_API_KEY. Cada busca e cada transcrição gastam 1 crédito.
  api            YouTube Data API v3 com YOUTUBE_API_KEY (só para buscar; a legenda vem por outra fonte).

Só biblioteca padrão + o executável yt-dlp.

Desenvolvido por Guilherme Carlos da Silva
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

HOME = Path.home()
EXTRA_PATH = [str(HOME / ".local" / "bin"), r"C:\Program Files\nodejs"]
UA = "ClaudeCode/estudar-assunto"


# ---------------------------------------------------------------- utilidades

def yt_dlp(*args: str) -> list[str]:
    """Monta o comando do yt-dlp; o runtime node só entra se estiver instalado."""
    tem_node = shutil.which("node", path=os.pathsep.join(EXTRA_PATH + [os.environ.get("PATH", "")]))
    return ["yt-dlp", *(["--js-runtimes", "node"] if tem_node else []), *args]


def env_com_path() -> dict:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(EXTRA_PATH + [env.get("PATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def chave(nome: str) -> str | None:
    """Lê a chave da variável de ambiente. Nunca imprime o valor."""
    return os.environ.get(nome) or None


def http_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def num_de_texto(texto: str | None) -> int | None:
    """'1,234,567 views' ou '1.234.567 visualizações' -> 1234567. Abreviações (1.2M) -> None."""
    if not texto:
        return None
    if re.search(r"\d\s*[KkMmBb]\b|mil\b|mi\b", texto):
        return None
    digitos = re.sub(r"[^\d]", "", texto)
    return int(digitos) if digitos else None


def segundos_de_texto(texto: str | None) -> int | None:
    """'1:02:03' -> 3723."""
    if not texto or not re.fullmatch(r"[\d:]+", texto.strip()):
        return None
    total = 0
    for parte in texto.strip().split(":"):
        total = total * 60 + int(parte)
    return total


def segundos_iso8601(texto: str | None) -> int | None:
    """'PT1H2M3S' -> 3723."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", texto or "")
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def mmss(seg: float) -> str:
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------- buscar

def buscar_ytdlp(consulta: str, n: int) -> list[dict]:
    cmd = yt_dlp("--flat-playlist", "-J", f"ytsearch{n}:{consulta}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env_com_path())
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp falhou na busca '{consulta}': {r.stderr.strip()[-400:]}")
    saida = []
    for e in json.loads(r.stdout).get("entries", []):
        saida.append({
            "id": e.get("id"),
            "titulo": e.get("title"),
            "canal": e.get("channel") or e.get("uploader"),
            "canal_id": e.get("channel_id"),
            "views": e.get("view_count"),
            "duracao_s": int(e["duration"]) if e.get("duration") else None,
            "verificado": e.get("channel_is_verified"),
        })
    return saida


def buscar_transcriptapi(consulta: str, n: int) -> list[dict]:
    k = chave("TRANSCRIPT_API_KEY")
    if not k:
        raise RuntimeError("TRANSCRIPT_API_KEY não encontrada.")
    url = "https://transcriptapi.com/api/v2/youtube/search?" + urllib.parse.urlencode(
        {"q": consulta, "type": "video", "limit": min(n, 50)})
    dados = http_json(url, {"Authorization": f"Bearer {k}"})
    saida = []
    for e in dados.get("results", []):
        if e.get("isLive"):
            continue
        saida.append({
            "id": e.get("videoId"),
            "titulo": e.get("title"),
            "canal": e.get("channelTitle"),
            "canal_id": e.get("channelId"),
            "views": num_de_texto(e.get("viewCountText")),
            "duracao_s": segundos_de_texto(e.get("lengthText")),
            "verificado": e.get("channelVerified"),
        })
    return saida


def buscar_api(consulta: str, n: int) -> list[dict]:
    k = chave("YOUTUBE_API_KEY")
    if not k:
        raise RuntimeError("YOUTUBE_API_KEY não encontrada (crie no Google Cloud e defina a variável de ambiente YOUTUBE_API_KEY).")
    base = "https://www.googleapis.com/youtube/v3/"
    busca = http_json(base + "search?" + urllib.parse.urlencode(
        {"part": "snippet", "q": consulta, "type": "video", "maxResults": min(n, 50), "key": k}))
    ids = [i["id"]["videoId"] for i in busca.get("items", []) if i.get("id", {}).get("videoId")]
    if not ids:
        return []
    videos = http_json(base + "videos?" + urllib.parse.urlencode(
        {"part": "snippet,statistics,contentDetails", "id": ",".join(ids), "key": k}))
    return [api_item_para_candidato(v) for v in videos.get("items", [])]


def api_item_para_candidato(v: dict) -> dict:
    sn, st, cd = v.get("snippet", {}), v.get("statistics", {}), v.get("contentDetails", {})
    return {
        "id": v.get("id"),
        "titulo": sn.get("title"),
        "canal": sn.get("channelTitle"),
        "canal_id": sn.get("channelId"),
        "views": int(st["viewCount"]) if st.get("viewCount") else None,
        "duracao_s": segundos_iso8601(cd.get("duration")),
        "verificado": None,
        "data": (sn.get("publishedAt") or "")[:10] or None,
        "curtidas": int(st["likeCount"]) if st.get("likeCount") else None,
    }


def enriquecer_ytdlp(c: dict) -> dict:
    """Completa com inscritos, data, curtidas e as legendas disponíveis."""
    url = f"https://www.youtube.com/watch?v={c['id']}"
    cmd = yt_dlp("--skip-download", "-J", url)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env_com_path())
    if r.returncode != 0:
        c["erro_enriquecer"] = r.stderr.strip()[-300:]
        return c
    d = json.loads(r.stdout)
    data = d.get("upload_date")
    c.update({
        "titulo": d.get("title") or c.get("titulo"),  # a busca pode trazer o título traduzido pelo YouTube
        "inscritos": d.get("channel_follower_count"),
        "data": f"{data[:4]}-{data[4:6]}-{data[6:]}" if data else c.get("data"),
        "curtidas": d.get("like_count", c.get("curtidas")),
        "idioma": d.get("language"),
        "capitulos": len(d.get("chapters") or []),
        "canal": c.get("canal") or d.get("channel") or d.get("uploader"),
        "views": c.get("views") if c.get("views") is not None else d.get("view_count"),
        "duracao_s": c.get("duracao_s") if c.get("duracao_s") is not None else (int(d["duration"]) if d.get("duration") else None),
        "legendas_manuais": sorted((d.get("subtitles") or {}).keys()),
        "legendas_auto_originais": sorted(k for k in (d.get("automatic_captions") or {}) if k.endswith("-orig")),
        "descricao": (d.get("description") or "")[:500],
    })
    return c


def cmd_buscar(a: argparse.Namespace) -> int:
    fonte = {"ytdlp": buscar_ytdlp, "transcriptapi": buscar_transcriptapi, "api": buscar_api}[a.fonte]
    todos: dict[str, dict] = {}
    avisos = []
    for q in a.consulta:
        try:
            resultados = fonte(q, a.por_consulta)
        except Exception as e:  # segue com as outras consultas
            avisos.append(str(e))
            continue
        for c in resultados:
            if not c.get("id"):
                continue
            atual = todos.setdefault(c["id"], {**c, "consultas": []})
            atual["consultas"].append(q)
    lista = list(todos.values())
    descartes = {"sem_views": 0, "abaixo_do_piso": 0, "sem_duracao": 0, "curto_demais": 0}
    filtrados = []
    for c in lista:
        if c.get("views") is None:
            descartes["sem_views"] += 1
        elif c["views"] < a.min_views:
            descartes["abaixo_do_piso"] += 1
        elif c.get("duracao_s") is None:
            descartes["sem_duracao"] += 1
        elif c["duracao_s"] < a.min_duracao:
            descartes["curto_demais"] += 1
        else:
            filtrados.append(c)
    filtrados.sort(key=lambda c: (len(c["consultas"]), c["views"]), reverse=True)
    if a.enriquecer and a.fonte != "transcriptapi":
        for c in filtrados[: a.enriquecer]:
            enriquecer_ytdlp(c)
    saida = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": a.fonte,
        "consultas": a.consulta,
        "criterios": {"min_views": a.min_views, "min_duracao_s": a.min_duracao},
        "total_encontrado": len(lista),
        "descartes": descartes,
        "avisos": avisos,
        "candidatos": filtrados,
    }
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in saida.items() if k != "candidatos"} | {
        "candidatos_aprovados": len(filtrados), "arquivo": str(a.saida)}, ensure_ascii=False, indent=2))
    return 0 if filtrados or not avisos else 2


def cmd_enriquecer(a: argparse.Namespace) -> int:
    """Completa no candidatos.json os vídeos escolhidos que ficaram sem dados do canal."""
    arq = Path(a.candidatos)
    dados = json.loads(arq.read_text(encoding="utf-8"))
    por_id = {c["id"]: c for c in dados["candidatos"]}
    feitos, faltando = [], []
    for vid in a.ids:
        c = por_id.get(vid)
        if c is None:
            faltando.append(vid)
            continue
        if "legendas_auto_originais" not in c or a.forcar:
            enriquecer_ytdlp(c)
        feitos.append({"id": vid, "inscritos": c.get("inscritos"), "data": c.get("data"),
                       "capitulos": c.get("capitulos"), "erro": c.get("erro_enriquecer")})
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"enriquecidos": feitos, "ids_fora_do_arquivo": faltando}, ensure_ascii=False, indent=2))
    return 0 if feitos else 2


# ---------------------------------------------------------------- transcrever

TAG = re.compile(r"<[^>]+>")
TEMPO = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{3}) -->")


def vtt_para_trechos(texto: str, rolante: bool = True) -> list[tuple[float, str]]:
    """Lê VTT e devolve (início, linha).

    rolante=True (legenda automática): remove a repetição que a legenda rolante cria nos cues seguintes.
    rolante=False (legenda manual): mantém todo cue, porque ali repetição é fala de verdade.
    """
    trechos, inicio = [], 0.0
    vistas: deque[str] = deque(maxlen=3)  # a legenda rolante repete a linha nos 2 ou 3 cues seguintes; fala repetida de verdade fica
    ultima = ""
    for linha in texto.splitlines():
        m = TEMPO.match(linha)
        if m:
            h, mi, s, ms = map(int, m.groups())
            inicio = h * 3600 + mi * 60 + s + ms / 1000
            continue
        if not linha.strip() or linha.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in linha:
            continue
        limpa = TAG.sub("", linha).replace("&nbsp;", " ").replace("&amp;", "&").strip()
        if not limpa or (rolante and (limpa == ultima or limpa in vistas)):
            continue
        vistas.append(limpa)
        trechos.append((inicio, limpa))
        ultima = limpa
    return trechos


def agrupar(trechos: list[tuple[float, str]], bloco_s: int = 30) -> list[str]:
    paragrafos, atual, marco = [], [], None
    for t, linha in trechos:
        if marco is None:
            marco = t
        if t - marco >= bloco_s and atual:
            paragrafos.append(f"[{mmss(marco)}] " + " ".join(atual))
            atual, marco = [], t
        atual.append(linha)
    if atual:
        paragrafos.append(f"[{mmss(marco or 0)}] " + " ".join(atual))
    return paragrafos


def escolher_trilha(idioma_video: str | None, manuais: list[str], auto_orig: list[str]) -> tuple[str, str] | None:
    """Decide qual legenda representa a FALA ORIGINAL do vídeo. Devolve (código, tipo) ou None.

    Só aceita trilha no idioma do vídeo. Legenda manual em outro idioma é tradução e é recusada,
    assim como as trilhas "-orig" de outros idiomas (dublagem automática).
    Códigos manuais podem ter sufixo com dígitos (ex.: "en-ehkg1hFWq8A").
    """
    base = (idioma_video or "").split("-")[0].lower()
    if not base:
        # Sem o idioma declarado, só dá para confiar quando existe uma única trilha "-orig".
        return (auto_orig[0], "automatica-original") if len(auto_orig) == 1 else None
    def prefixo(cod: str) -> str:
        return cod.split("-")[0].lower()
    manual = [m for m in manuais if prefixo(m) == base and not m.endswith("-orig")]
    if manual:
        exato = [m for m in manual if m.lower() in (base, (idioma_video or "").lower())]
        return (exato or sorted(manual))[0], "manual"
    auto = [x for x in auto_orig if prefixo(x) == base]
    if auto:
        return sorted(auto, key=len)[0], "automatica-original"
    return None


def legenda_ytdlp(vid: str, c: dict) -> tuple[list[tuple[float, str]], str]:
    escolha = escolher_trilha(c.get("idioma"), c.get("legendas_manuais") or [], c.get("legendas_auto_originais") or [])
    if escolha is None:
        if not c.get("idioma"):
            return [], "idioma do vídeo desconhecido; sem como garantir a fala original (tente --fonte transcriptapi)"
        return [], f"sem legenda no idioma original ({c.get('idioma')}); traduções foram recusadas"
    codigo, tipo = escolha
    flag = "--write-subs" if tipo == "manual" else "--write-auto-subs"
    tmp = Path(tempfile.mkdtemp(prefix="estudar_vtt_"))
    try:
        cmd = yt_dlp("--skip-download", flag, "--sub-langs", f"^{re.escape(codigo)}$",
               "--sub-format", "vtt", "-o", str(tmp / "%(id)s.%(ext)s"), f"https://www.youtube.com/watch?v={vid}")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env_com_path())
        arquivos = sorted(tmp.glob(f"*.{codigo}.vtt"))
        if not arquivos:
            return [], f"falha ao baixar a trilha {codigo}: {r.stderr.strip()[-200:]}"
        rolante = tipo != "manual"
        return vtt_para_trechos(arquivos[0].read_text(encoding="utf-8"), rolante), f"{tipo} ({codigo})"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def legenda_transcriptapi(vid: str) -> tuple[list[tuple[float, str]], str]:
    k = chave("TRANSCRIPT_API_KEY")
    if not k:
        raise RuntimeError("TRANSCRIPT_API_KEY não encontrada.")
    url = "https://transcriptapi.com/api/v2/youtube/transcript?" + urllib.parse.urlencode(
        {"video_url": vid, "format": "json", "include_timestamp": "true"})
    d = http_json(url, {"Authorization": f"Bearer {k}"})
    trechos = [(float(t.get("start", 0)), t.get("text", "").strip()) for t in d.get("transcript", [])]
    return [t for t in trechos if t[1]], f"transcriptapi ({d.get('language', '?')})"


def cmd_transcrever(a: argparse.Namespace) -> int:
    pasta = Path(a.saida)
    pasta.mkdir(parents=True, exist_ok=True)
    meta = {}
    if a.candidatos and Path(a.candidatos).exists():
        for c in json.loads(Path(a.candidatos).read_text(encoding="utf-8"))["candidatos"]:
            meta[c["id"]] = c
    relatorio = []
    for vid in a.ids:
        c = meta.get(vid) or {"id": vid}
        try:
            if a.fonte == "transcriptapi":
                trechos, origem = legenda_transcriptapi(vid)
            else:
                if "legendas_auto_originais" not in c:
                    enriquecer_ytdlp(c)  # traz idioma, trilhas disponíveis e título original
                trechos, origem = legenda_ytdlp(vid, c)
        except Exception as e:
            relatorio.append({"id": vid, "ok": False, "erro": str(e)[-300:]})
            continue
        if not trechos:
            relatorio.append({"id": vid, "ok": False, "erro": origem})
            continue
        cab = [
            f"# {c.get('titulo', vid)}",
            "",
            f"- Canal: {c.get('canal', 'n/d')} ({c.get('inscritos', 'n/d')} inscritos)",
            f"- Link: https://www.youtube.com/watch?v={vid}",
            f"- Views: {c.get('views', 'n/d')} · Data: {c.get('data', 'n/d')} · Duração: {mmss(c['duracao_s']) if c.get('duracao_s') else 'n/d'}",
            f"- Legenda: {origem} · Transcrito em {datetime.now():%Y-%m-%d}",
            "",
            "A minutagem entre colchetes permite citar o trecho: link + `&t=<segundos>s`.",
            "",
        ]
        corpo = agrupar(trechos)
        rodape = ["", "---", "Skill estudar-assunto · Desenvolvido por Guilherme Carlos da Silva"]
        arq = pasta / f"{vid}.md"
        arq.write_text("\n".join(cab + corpo + rodape) + "\n", encoding="utf-8")
        palavras = sum(len(p.split()) for p in corpo)
        relatorio.append({"id": vid, "ok": True, "arquivo": str(arq), "legenda": origem, "palavras": palavras})
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    return 0 if any(r["ok"] for r in relatorio) else 2


# ---------------------------------------------------------------- main

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("buscar", help="busca, filtra e enriquece candidatos")
    b.add_argument("--consulta", action="append", required=True, help="repita para várias consultas")
    b.add_argument("--fonte", choices=["ytdlp", "transcriptapi", "api"], default="ytdlp")
    b.add_argument("--por-consulta", type=int, default=25)
    b.add_argument("--min-views", type=int, default=10000)
    b.add_argument("--min-duracao", type=int, default=480, help="segundos; 480 = 8 min")
    b.add_argument("--enriquecer", type=int, default=20, help="quantos dos melhores ganham dados do canal")
    b.add_argument("--saida", required=True)
    b.set_defaults(func=cmd_buscar)

    e = sub.add_parser("enriquecer", help="completa inscritos, data, capítulos e legendas dos escolhidos")
    e.add_argument("ids", nargs="+")
    e.add_argument("--candidatos", required=True)
    e.add_argument("--forcar", action="store_true", help="refaz mesmo quem já tem dados")
    e.set_defaults(func=cmd_enriquecer)

    t = sub.add_parser("transcrever", help="baixa a legenda e grava um .md por vídeo")
    t.add_argument("ids", nargs="+")
    t.add_argument("--fonte", choices=["ytdlp", "transcriptapi"], default="ytdlp")
    t.add_argument("--candidatos", help="candidatos.json, para o cabeçalho de cada transcrição")
    t.add_argument("--saida", required=True)
    t.set_defaults(func=cmd_transcrever)

    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
