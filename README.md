# Skills de vídeo e áudio para o Claude Code

**Desenvolvido por Guilherme Carlos da Silva**

## O que é

O Claude não assiste vídeo nem escuta áudio. Ele lê texto e olha imagens. Este pacote ensina o **Claude Code** a fazer a ponte: ele baixa o vídeo, transforma a fala em texto com a minutagem e a imagem em quadros. Com isso o Claude consegue resumir, citar, analisar e estudar qualquer vídeo ou áudio como se tivesse assistido.

Tudo roda no seu computador e é de graça. Nenhum áudio é enviado para serviço de transcrição pago.

## O que faz

### 🎬 ler-video

Você cola o link de um **reel ou post do Instagram, vídeo do YouTube, Shorts, TikTok**, ou manda um arquivo de vídeo. A skill:

1. baixa o vídeo (ou as fotos, se for carrossel);
2. transcreve a fala, com a minutagem `[mm:ss]` de cada trecho;
3. tira um quadro em resolução cheia a cada 2 segundos, com o tempo exato no nome do arquivo;
4. separa um quadro em cada troca de cena, para ver o ritmo da edição;
5. monta folhas de contato (o vídeo inteiro em miniaturas, numa imagem só);
6. junta tudo num relatório com autor, data, curtidas, comentários e a legenda do post.

Serve para entender rápido do que um vídeo fala, para tirar o texto de um tutorial e, principalmente, para **estudar uma referência**: o Claude descreve o gancho, a fonte, as cores, os cortes e o que a fala faz em cada parte, e diz o que dá para copiar e o que adaptar.

**Como pedir:** "olha esse reel: <link>", "o que tem nesse vídeo?", "quero fazer um igual a esse" ou `/ler-video`.

### 🎙️ transcrever-audio

Áudio do WhatsApp (.ogg/.opus), gravação de reunião, aula, MP3 ou vídeo que já está no computador vira **texto com minutagem** e **legenda `.srt`** pronta para editor de vídeo. Aceita vários arquivos de uma vez. Depois o Claude entrega o que você pedir: texto limpo, resumo, ata ou lista do que foi combinado.

**Como pedir:** "transcreve esse áudio", "o que ele falou nesse áudio?", "faz a legenda desse vídeo" ou `/transcrever-audio`.

### 📚 estudar-assunto

Você diz um tema e o Claude vira especialista nele. A skill busca os melhores vídeos do YouTube sobre o assunto, dá nota de autoridade a cada um (quem fala, profundidade, recepção) e escolhe de 6 a 10 vídeos de pelo menos 4 autores diferentes. Depois transcreve só a fala original, sem tradução automática, e monta uma **skill nova** com os métodos que eles ensinam. Junto vêm a lista de fontes e a lista do que ainda precisa ser conferido.

**Como pedir:** "vira especialista em X", "estuda X no YouTube" ou `/estudar-assunto`.

## Instalar (uma vez só)

Feito para **Windows + Claude Code**. Abra o **PowerShell** e rode um bloco por vez.

**1. Programas de base** (Python, ffmpeg, Node e Git):
```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install OpenJS.NodeJS.LTS
winget install Git.Git
```
Feche e abra o PowerShell de novo depois disso, para ele enxergar os programas novos. Confira se está tudo lá:
```powershell
python --version
ffmpeg -version
node --version
git --version
```
Cada um tem de responder com um número de versão. Se o `python` abrir a Microsoft Store em vez de responder, vá em Configurações → Aplicativos → Configurações avançadas de aplicativo → Aliases de execução de aplicativo, desligue os dois "python", feche e abra o PowerShell e teste de novo.

**2. Ferramentas de download e transcrição:**
```powershell
python -m pip install -U "yt-dlp[default,curl-cffi]" gallery-dl faster-whisper "av<19"
```
O `curl-cffi` é o que deixa o yt-dlp baixar do TikTok. O `"av<19"` segura uma peça do faster-whisper numa versão compatível: a 19 quebra a transcrição.

**3. As skills:**
```powershell
Remove-Item -Recurse -Force "$env:TEMP\skills-video-audio" -ErrorAction SilentlyContinue
git clone https://github.com/Guiair21/skills-video-audio.git "$env:TEMP\skills-video-audio"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
foreach ($s in "ler-video", "transcrever-audio", "estudar-assunto") { Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\skills\$s" -ErrorAction SilentlyContinue }
Copy-Item -Recurse -Force "$env:TEMP\skills-video-audio\skills\*" "$env:USERPROFILE\.claude\skills\"
```

**4. Conferir:** abra o Claude Code e pergunte "quais skills você tem?". As três devem aparecer.

A primeira transcrição demora mais, porque baixa o modelo do Whisper (uns 500 MB). Das próximas vezes ele já está no computador.

## Instagram: o login

O Instagram só deixa baixar com login. O jeito seguro é exportar os cookies do navegador para um arquivo:

1. Entre no instagram.com pelo Chrome. De preferência numa **conta secundária**, só para pesquisa, porque se baixar demais o Instagram bloqueia por um tempo a conta usada.
2. Instale a extensão **Get cookies.txt LOCALLY** na Chrome Web Store.
3. Com o instagram.com aberto, clique na extensão e em **Export**. Vai baixar um `cookies.txt`.
4. Crie a pasta `C:\Users\<seu usuário>\.secrets\` e salve o arquivo lá com o nome **`instagram-cookies.txt`**. A skill procura nesse lugar sozinha.

> ⚠️ **Esse arquivo vale a senha da sua conta.** Não mande para ninguém, não cole no chat, não suba para o GitHub e não deixe em pasta sincronizada. Se vazar, saia de todas as sessões no Instagram (Configurações → Central de Contas → Senha e segurança → Onde você está conectado).

O login vence de tempos em tempos e quando você troca a senha. Quando der erro de login, **primeiro atualize as ferramentas** (`python -m pip install -U "yt-dlp[default,curl-cffi]" gallery-dl`), que é a causa mais comum. Se continuar, exporte o cookie de novo.

## YouTube com crédito (opcional)

Às vezes o YouTube bloqueia o yt-dlp por algumas horas. Para esses casos existe a **youtube-full**, uma skill da [TranscriptAPI](https://transcriptapi.com), com conta grátis de 100 créditos. Ela é de terceiros, precisa de chave própria e não faz parte deste pacote. A skill estudar-assunto usa essa chave sozinha se você criar a variável de ambiente:
```powershell
setx TRANSCRIPT_API_KEY "sua-chave-aqui"
```
Depois feche e abra de novo o PowerShell e o Claude Code, senão eles não enxergam a chave. Nunca escreva a chave dentro de um arquivo deste repositório.

## Onde ficam os arquivos

| Skill | Pasta |
|---|---|
| ler-video | `C:\Users\<seu usuário>\ler-video\<site>-<código>\` |
| transcrever-audio | ao lado do áudio, ou onde você pedir |
| estudar-assunto | `C:\Users\<seu usuário>\estudos\<assunto>\`, e a skill nova em `.claude\skills\<assunto>\` |

## Atualizar

Rode de novo o passo 3, que apaga a cópia antiga antes de baixar. Para atualizar as ferramentas: `python -m pip install -U "yt-dlp[default,curl-cffi]" gallery-dl faster-whisper "av<19"`.

## Uso responsável

Baixe para estudar e se inspirar, não para repostar conteúdo de outra pessoa. Respeite os termos de uso de cada plataforma.

## Créditos

Skills criadas e mantidas por **Guilherme Carlos da Silva**. Se usar, adaptar ou compartilhar, mantenha o crédito.

Ferramentas de código aberto usadas por baixo: [yt-dlp](https://github.com/yt-dlp/yt-dlp), [gallery-dl](https://github.com/mikf/gallery-dl), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) e [FFmpeg](https://ffmpeg.org).
