# Teledome: Telegram Download Media

Uma ferramenta **poderosa** de linha de comando (CLI) em Python para baixar mídias do Telegram (canais, grupos e fóruns com tópicos) aos quais a sua conta tem acesso — incluindo mídias em chats com **download protegido**.

Destaques do que ela consegue fazer:

- Listar chats da conta (inclui Principal, Arquivados e pastas do Telegram quando disponíveis)
- Baixar mídias com seleção por tipo: `photo`, `video`, `document`, `audio`, `voice`
- Suporte a fóruns: listar tópicos e baixar por tópico
- Baixar em lote e com barra de progresso
- Retomar execuções usando histórico local (SQLite) para evitar downloads duplicados
- Lidar com erros comuns automaticamente (por exemplo, `FloodWait` e falhas transitórias)

O processo é interativo: você escolhe o chat e, quando aplicável, tópicos, intervalo de mensagens e tipos de mídia.

Este projeto mantém um histórico local (SQLite) para evitar baixar novamente mídias já processadas.

Aviso: utilize apenas para conteúdos que você tem autorização para baixar e armazenar.

## Sumário

- Visão geral
- Requisitos
- Configuração (API_ID/API_HASH)
- Instalação
- Guia de uso (passo a passo)
- Saída e organização dos downloads
- Histórico e retomada
- Detalhes técnicos
- Limitações conhecidas
- Troubleshooting

## Visão geral

Principais características:

- Seleção de 1 ou mais chats (inclui chats em Arquivados e pastas do Telegram quando disponíveis)
- Suporte a fóruns: seleção de tópicos
- Seleção de tipos de mídia: `photo`, `video`, `document`, `audio`, `voice`
- Downloads com barra de progresso
- Retentativas automáticas para erros comuns (inclui `FloodWait`)
- Registro de itens baixados em `data/history.db`

## Requisitos

- Uma conta no Telegram.
- `API_ID` e `API_HASH` do Telegram (obtenha em https://my.telegram.org/auth?to=apps).
- `uv` (recomendado) para criar o ambiente e instalar dependências.
  - Observação (Windows): o script `run.cmd` tem uma instalação automática do `uv` que normalmente funciona.

## Configuração (API_ID / API_HASH)

Antes de continuar: se você baixou o projeto em um arquivo compactado (por exemplo, `.zip`), **descompacte** em uma pasta antes de executar os scripts.

O aplicativo lê as credenciais a partir de um arquivo `.env` na raiz do projeto.

- Se o projeto já veio com um `.env` na pasta, ele precisa ser **preenchido** com seus dados.
- Se não existir, crie um arquivo chamado `.env` na raiz do projeto.

Conteúdo esperado:

```env
API_ID=123456
API_HASH=abcdef0123456789abcdef0123456789
```

Como obter as credenciais (passo a passo no site):

1) Acesse https://my.telegram.org/auth?to=apps
2) Faça login com seu número
3) Abra a seção de “API development tools” (ou equivalente)
4) Crie um aplicativo (nome/descrição podem ser simples)
5) Copie os valores exibidos como **API ID** e **API Hash**

Observações:

- Esses valores são da API do Telegram (não são o seu número/senha).
- Não compartilhe o `.env`.

O aplicativo carrega o `.env` via `python-dotenv` no startup.

## Instalação

Este projeto inclui scripts para rodar com o mínimo de configuração.

### Windows (recomendado)

Na maioria dos casos, basta **dar duplo clique** em `run.cmd`.

- O script carrega o arquivo `.env`, valida as credenciais e cria o ambiente automaticamente.
- Se o `uv` não estiver instalado, ele tenta instalar via PowerShell (na maior parte dos casos dá certo).

Se você preferir rodar pelo Prompt de Comando, na pasta do projeto execute:

```bat
run.cmd
```

### Linux / macOS

```bash
chmod +x run.sh
./run.sh
```

Observação: o script exige que `uv` esteja disponível no PATH (https://github.com/astral-sh/uv).

### Instalação manual (alternativa)

Se preferir não usar `uv`, você pode utilizar `venv`/`pip`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Guia de uso (passo a passo)

Ao executar, o programa irá:

1) Limpa a pasta `cache/` (downloads temporários)
2) Inicializa o banco `data/history.db`
3) Inicia o cliente do Telegram e, na primeira vez, solicita autenticação

### 1) Autenticação (primeira execução)

Na primeira vez, o Telegram pode solicitar:

- Código enviado para sua conta
- Senha de verificação em duas etapas (se habilitada)

A sessão fica armazenada em `data/user_session.session`.

### 2) Seleção de chat(s)

O programa lista chats e solicita:

`Select chat(s) (number(s) or ID(s); comma separated)`

Você pode informar:

- Número(s) da lista (ex.: `1` ou `1,3,7`)
- ID(s) do chat (ex.: `-100...`)

Regra importante (sobre a etapa seguinte):

- Se mais de um chat for selecionado, o programa entra em modo multi-chat e, na próxima etapa, não solicita seleção de tópicos nem de intervalo (processa o intervalo completo disponível).

### 3) Seleção de tópicos (somente para fóruns e somente quando 1 chat é selecionado)

Se o chat selecionado for um Fórum, será exibida a lista de tópicos e solicitado:

`Select topics (comma separated numbers/IDs, ...; or 0 for All)`

- `0` = todos os tópicos
- `1,3,4` = tópicos por índice na lista
- também é possível informar IDs de tópico

Regra importante (sobre a etapa seguinte):

- Se mais de um tópico for selecionado, na próxima etapa a seleção de intervalo é ignorada e o download será feito no intervalo completo disponível.

### 4) Seleção de intervalo de mensagens (quando disponível)

Quando habilitado, o programa oferece:

1) All messages (opção padrão)
2) From specific ID (to newest)
3) Range (Start-End)

Os IDs informados são IDs de mensagem do Telegram.

Exemplos práticos:

- Para baixar do ID 15000 até o mais recente:
  - Escolha a opção `2` (From specific ID)
  - Informe `Enter start message ID`: `15000`
- Para baixar um intervalo específico:
  - Escolha a opção `3` (Range)
  - Informe `Enter start message ID`: `20000`
  - Informe `Enter end message ID`: `21000`

### 5) Seleção de tipos de mídia (última etapa)

Depois de definir chat/tópicos/intervalo (quando aplicável), o programa solicita:

`Select media types (comma separated numbers, e.g. 1,2)`

Mapeamento:

- `1` = photo
- `2` = video
- `3` = document
- `4` = audio
- `5` = voice

Pressionar Enter utiliza o padrão (todos os tipos).

## Saída e organização dos downloads

Diretórios usados:

- Temporários: `cache/` (é removido/recriado ao iniciar)
- Dados locais: `data/` (sessão e histórico)
- Downloads finais: `downloads/`

Estrutura do download final:

`downloads/<chat_id>/<topic_id|no_topic>/[<message_id>] <nome>.<ext>`

Notas sobre nomes de arquivos:

- Quando disponível, usa `file_name` original de documentos/vídeos/áudios.
- Caso não exista `file_name`, utiliza a primeira linha da legenda (`caption`) como base.
- Se não houver legenda, usa um nome padrão (`photo`, `video`, `document`, `audio`, `voice`).
- A extensão pode não existir em alguns casos (ex.: `document` sem `file_name`).

## Histórico e retomada

O histórico é armazenado em `data/history.db` (SQLite), tabela `downloads`, com chave primária `(message_id, chat_id, topic_id)`.

Comportamento:

- Itens já presentes na tabela são ignorados.
- Em modo de tópicos, a filtragem de IDs já processados é feita antes de buscar as mensagens.

Reset do histórico (opcional):

- Para forçar o reprocessamento, você pode:
  - apagar `data/history.db` (mais simples), ou
  - editar o banco e remover linhas específicas (para baixar novamente apenas alguns itens).

Para editar o banco, use um editor SQLite (por exemplo, “DB Browser for SQLite”) e remova registros da tabela `downloads` correspondentes ao item/chat/tópico desejado.

## Detalhes técnicos

### Fluxo principal

- Interface de linha de comando: `click` (interativo; não há flags/argumentos de configuração no momento)
- Cliente Telegram: PyroFork/Pyrogram
- Banco: `aiosqlite`
- Progresso: `tqdm`

### Descoberta de chats e tópicos

- Chats são listados via chamadas raw (`messages.GetDialogs`) e incluem principal, Arquivados e pastas do usuário.
- Em algumas contas, certas pastas podem falhar ao listar; nesses casos elas são ignoradas e a execução continua.
- Tópicos de fórum são obtidos via raw `messages.GetForumTopics`.
- Mensagens de um tópico são enumeradas via raw `messages.GetReplies`.

### Estratégia de varredura

- Sem filtro de tópico: varredura por intervalos de IDs em batches de 200 e consulta via `get_messages(chat_id, ids)`.
- Com filtro de tópico: coleta IDs pertencentes ao tópico e baixa por chunks (com filtragem adicional por histórico).

### Download, retentativas e integridade

- Cada download é feito inicialmente para `cache/` e depois movido para `downloads/`.
- O downloader tenta refazer o fetch da mensagem antes de cada tentativa para reduzir problemas de referência expirada.
- Política de retentativas (máx. 4):
  - `FloodWait`: aguarda o tempo indicado pelo Telegram
  - Erros transitórios (timeout/5xx/rede): backoff exponencial (1s → 30s)
  - Erros de referência/ID de arquivo: tenta atualizar a mensagem e repetir
- Verificação por tamanho: compara o tamanho do arquivo final com o `file_size` reportado quando disponível.

## Limitações conhecidas

- Chats grandes: a varredura por intervalo de IDs pode ser lenta e gerar muitas requisições.
- O cache (`cache/`) é limpo no início de cada execução; downloads incompletos não são retomados pelo arquivo temporário.
- Nem todo `document` terá extensão se o Telegram não fornecer `file_name`.

## Troubleshooting

### `API_ID and API_HASH must be set in .env file`

- Verifique se existe `.env` na raiz do projeto e se contém `API_ID` e `API_HASH`.

### Lista de chats vazia

- Confirme que você autenticou na conta correta.
- Confirme que a conta participa dos chats.

### `FloodWait`

- A execução aguarda e continua automaticamente. Em volumes grandes, isso é esperado.

### `FILE_REFERENCE_EXPIRED` (ou similares)

- O downloader tenta atualizar a mensagem e repetir. Se persistir, execute novamente; o histórico impede retrabalho.

### “Size mismatch”

- O arquivo é apagado e o download é repetido até o limite de tentativas.

### O script fica “travado” por muito tempo e depois aparecem erros de rede

Em alguns ambientes, isso pode acontecer por **relógio do sistema desincronizado** (hora/data erradas), o que afeta conexões seguras e pode causar timeouts.

Como sincronizar:

- Windows 10/11:
  - Configurações → Hora e idioma → Data e hora
  - Ative “Ajustar hora automaticamente” e clique em “Sincronizar agora”
- Linux (systemd):
  - Verifique: `timedatectl status`
  - Ative NTP: `sudo timedatectl set-ntp true`

Em casos mais raros, o problema pode estar relacionado a **firewall**, proxy corporativo ou bloqueio de rede/ISP. Se a sincronização do relógio não resolver, teste em outra rede.

## Privacidade e segurança

- `data/user_session.session` permite acesso ao Telegram pela sua conta. Não compartilhe a pasta `data/`.
- Não publique o arquivo `.env`.

## Licença

MIT

## Créditos

- Matheus Bach (https://github.com/matheusbach)
