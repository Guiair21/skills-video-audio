# Baixar vários reels de um perfil do Instagram

Para estudar um perfil inteiro (o que dá certo, como o autor edita), o gallery-dl baixa em lote. Use com moderação: baixar muito rápido faz o Instagram bloquear a conta por um tempo. Prefira uma conta secundária, só para pesquisa.

## Comando

```bash
gallery-dl --cookies "$HOME/.secrets/instagram-cookies.txt" \
  --range "1-30" --sleep-request "3-6" \
  --download-archive "<pasta>/baixados.txt" \
  -f "{date:%Y-%m-%d}_{shortcode}.{extension}" \
  -D "<pasta>" "https://www.instagram.com/<perfil>/reels/"
```

- `--range "1-30"`: os 30 mais recentes. Comece pequeno.
- `--sleep-request "3-6"`: pausa de 3 a 6 segundos entre pedidos. Não tire.
- `--download-archive`: lembra o que já baixou. Rodar de novo depois pega só os novos.

## Depois de baixar

Para cada vídeo da pasta, rode o `ler_video.py` com o caminho do arquivo e `--sem-quadros` se só quiser a fala. Para a fala de muitos de uma vez, a skill transcrever-audio aceita vários arquivos no mesmo comando e carrega o modelo uma vez só.

## Quando dá erro

| Sintoma | Correção |
|---|---|
| `HTTP redirect to home page` na listagem do perfil | atualize primeiro: `python -m pip install -U gallery-dl` |
| Alguns reels falham com "Cannot import yt-dlp" | baixe esses um por um pela URL `https://www.instagram.com/reel/<código>/`, com `--sleep-request` maior |
| Erro 401 ou pedido de login | o cookie venceu; exporte de novo (README do repositório) |
| Para achar até onde baixar | `gallery-dl -j ... --range 1-300` lista só os dados, sem baixar |
