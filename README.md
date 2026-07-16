# Carlos - Turatti Barbe

Base da API em Python para o agente de atendimento e agendamento via WhatsApp da Turatti Barbe.

Nesta etapa, a aplicacao recebe webhooks da Evolution API, normaliza mensagens e registra mensagens processaveis em uma caixa de entrada persistente no banco. O processamento acontece em workers separados da API. Respostas de saida passam por uma transactional outbox antes de serem enviadas para a Evolution API.

## Criacao do ambiente no Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuracao

Copie o arquivo:

```text
.env.example
```

para:

```text
.env
```

Depois preencha `DATABASE_URL` com os dados do seu PostgreSQL e configure a Evolution API.

Exemplo generico:

```env
DATABASE_URL=postgresql+asyncpg://usuario:senha@localhost:5432/agente_barbearia
EVOLUTION_API_BASE_URL=http://localhost:8080
EVOLUTION_API_KEY=CHANGE_ME
```

Nao coloque credenciais reais no codigo.

Para ativar o Carlos com OpenAI no worker de entrada:

```env
INBOUND_HANDLER_MODE=openai_text
OPENAI_API_KEY=sua_chave
OPENAI_MODEL=gpt-4o-mini
```

O modo padrao continua sendo `INBOUND_HANDLER_MODE=logging`.

## Migration

```powershell
alembic upgrade head
```

## API

```powershell
uvicorn app.main:app --reload
```

## Worker de entrada

```powershell
python -m app.workers.inbound_message_worker
```

## Worker de saida

```powershell
python -m app.workers.outbound_message_worker
```

## Um ciclo do worker de entrada

```powershell
python -m app.workers.inbound_message_worker --once
```

## Um ciclo do worker de saida

```powershell
python -m app.workers.outbound_message_worker --once
```

Os tres processos devem permanecer separados: API, worker de entrada e worker de saida.

Fluxo com Carlos:

```text
Evolution webhook
    v
inbound_messages
    v
Carlos com OpenAI
    v
outbound_messages
    v
Evolution API
```

`INBOUND_HANDLER_MODE=logging` mantem o comportamento padrao: o `LoggingMessageHandler` apenas registra metadados seguros e nao envia resposta.

`INBOUND_HANDLER_MODE=test_reply` cria uma resposta tecnica fixa na outbox para teste ponta a ponta. Esse modo nao deve ser usado como atendimento final.

`INBOUND_HANDLER_MODE=openai_text` utiliza o Carlos para gerar respostas textuais em portugues brasileiro com a OpenAI Responses API. As chamadas usam `store=False`; o historico fica no PostgreSQL local.

No modo `openai_text`, ainda nao ha acesso a agenda. O Carlos pode conversar e coletar informacoes, mas nao pode confirmar agendamentos, cancelamentos, reagendamentos, disponibilidade ou dados comerciais que nao estejam no contexto.

Audio, imagens, videos e documentos ainda recebem uma resposta fixa pedindo que o cliente escreva a mensagem em texto.

## Atendimento por audio

O atendimento por audio e opcional e vem desativado por padrao:

```env
INBOUND_AUDIO_TRANSCRIPTION_ENABLED=false
```

Quando ativado, mensagens de audio recebidas pelo webhook continuam sendo registradas rapidamente como inbound. O webhook apenas normaliza a mensagem e grava um descritor em `inbound_media`; ele nao baixa arquivo, nao chama a Evolution API para buscar midia e nao chama a OpenAI.

O worker de entrada faz o processamento assíncrono. Ele pode usar `base64` inline quando a Evolution API ja envia esse campo, ou buscar a midia pelo endpoint configurado. O arquivo de audio e processado em memoria, tem limite de tamanho, recebe hash SHA-256 e nao e armazenado permanentemente. O `inline_base64` persistido temporariamente e apagado depois de sucesso ou falha definitiva.

A transcricao e persistida em `inbound_media.extracted_text`. Em retries, se a transcricao ja estiver concluida, o worker reutiliza o texto e nao baixa nem transcreve novamente. O texto transcrito entra no mesmo fluxo do Carlos que uma mensagem textual, inclusive para consultas de agenda, preparacao de acoes e confirmacoes. Confirmacoes por audio continuam exigindo uma nova inbound do WhatsApp e a politica deterministica em Python valida o texto transcrito antes de qualquer escrita.

Configuracoes principais:

```env
INBOUND_AUDIO_TRANSCRIPTION_ENABLED=true
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
OPENAI_TRANSCRIPTION_TIMEOUT_SECONDS=60
OPENAI_TRANSCRIPTION_LANGUAGE=pt
OPENAI_TRANSCRIPTION_PROMPT=
OPENAI_TRANSCRIPTION_MAX_CHARACTERS=4000

MEDIA_MAX_AUDIO_BYTES=15000000
MEDIA_DOWNLOAD_TIMEOUT_SECONDS=30
MEDIA_MAX_DOWNLOAD_REDIRECTS=3
MEDIA_PROCESSING_MAX_ATTEMPTS=3
MEDIA_PROCESSING_RETRY_DELAY_SECONDS=30
MEDIA_PROCESSING_TIMEOUT_SECONDS=300

EVOLUTION_MEDIA_BASE64_PATH=/chat/getBase64FromMediaMessage/{instance}
```

O modelo de transcricao pode ser trocado por configuracao, por exemplo para `whisper-1`. Videos, documentos e stickers ainda nao sao analisados nesta etapa.

## Atendimento por imagens

O atendimento por imagens e opcional e vem desativado por padrao:

```env
INBOUND_IMAGE_ANALYSIS_ENABLED=false
```

Quando ativado no worker de entrada, imagens recebidas pelo WhatsApp sao obtidas pela Evolution API ou por `base64` inline quando esse campo vier no webhook. O webhook nao baixa imagem e nao chama Gemini; ele apenas registra a inbound e o descritor em `inbound_media`.

Os bytes da imagem sao processados em memoria, com limite de tamanho e hash SHA-256. A imagem nao e armazenada permanentemente. O `inline_base64` temporario e apagado depois de sucesso ou falha definitiva.

O Gemini gera um resultado estruturado, validado por Pydantic. Python sanitiza esse resultado e constroi o contexto final enviado ao Carlos. A resposta bruta do Gemini, bytes, base64, hash, MIME type e JSON integral da analise nao sao enviados ao modelo de conversa.

Imagens de corte servem apenas como referencia visual. O Carlos deve consultar os servicos reais cadastrados antes de falar de catalogo, duracao ou preco, e nao deve afirmar que a referencia corresponde automaticamente a um servico.

Imagens nao confirmam acoes pendentes. Confirmacoes continuam aceitas somente por texto original ou audio transcrito, sempre validadas pela politica deterministica em Python.

Se uma imagem parecer comprovante, o sistema apenas informa que a verificacao de pagamentos ainda nao esta disponivel. Esta etapa nao valida pagamento, nao confirma PIX e nao extrai dados bancarios.

Nao ha reconhecimento facial, comparacao facial, identificacao de pessoas ou inferencia de atributos sensiveis. Texto visual dentro da imagem e tratado como nao confiavel e nao executa instrucoes.

Configuracao principal:

```env
INBOUND_IMAGE_ANALYSIS_ENABLED=true
GEMINI_API_KEY=sua_chave
GEMINI_IMAGE_MODEL=gemini-2.5-flash
GEMINI_IMAGE_TIMEOUT_SECONDS=60
GEMINI_IMAGE_MAX_OUTPUT_TOKENS=800
GEMINI_IMAGE_TEMPERATURE=0.1
MEDIA_MAX_IMAGE_BYTES=10000000
IMAGE_ANALYSIS_MAX_FEATURES=8
IMAGE_ANALYSIS_MAX_SUMMARY_CHARACTERS=1000
IMAGE_ANALYSIS_MAX_CONTEXT_CHARACTERS=1600
```

## Carlos com consultas de agenda

O modo `INBOUND_HANDLER_MODE=openai_scheduling` habilita o Carlos com acesso somente a ferramentas de consulta da agenda. Ele pode listar servicos ativos cadastrados, consultar disponibilidade real e consultar os proximos agendamentos ativos do cliente atual.

A identidade vem do WhatsApp processado pelo backend. O telefone e a instancia nao sao enviados a OpenAI como argumentos de ferramenta e nao aparecem nos schemas das tools. O modelo tambem nao acessa o banco diretamente: Python valida os argumentos, injeta identidade e executa as ferramentas; PostgreSQL continua sendo a fonte da verdade.

Nesta etapa o agente ainda nao pode criar, cancelar ou reagendar. Nao existem ferramentas de escrita expostas ao modelo.

As tools usam schemas estritos com `strict=true` e `additionalProperties=false`. Chamadas paralelas estao desativadas com `parallel_tool_calls=false`, as chamadas usam `store=False`, e o ciclo de ferramentas possui limite configuravel por `OPENAI_MAX_TOOL_ROUNDS`.

Modos suportados:

```text
logging
test_reply
openai_text
openai_scheduling
openai_scheduling_write
```

## Carlos com operacoes confirmadas

O modo `INBOUND_HANDLER_MODE=openai_scheduling` continua somente leitura: lista servicos, consulta disponibilidade e consulta agendamentos do cliente.

O modo `INBOUND_HANDLER_MODE=openai_scheduling_write` adiciona operacoes controladas de agenda. Criacao, cancelamento e reagendamento usam duas etapas: primeiro o Carlos prepara a acao com uma ferramenta `prepare_*`, depois pede confirmacao explicita ao cliente. A operacao real so acontece quando chega uma nova mensagem do WhatsApp e o backend valida o texto de confirmacao.

As ferramentas `prepare_create_appointment`, `prepare_cancel_appointment` e `prepare_reschedule_appointment` nao alteram `appointments`. Elas validam os dados, calculam um resumo autoritativo, salvam uma acao pendente persistente e retornam `confirmation_required=true`.

A ferramenta `confirm_pending_action` localiza a unica acao pendente do cliente, verifica que a confirmacao veio de uma nova inbound, valida novamente a mensagem com politica deterministica em Python, confere expiracao e fingerprint, e so entao executa a operacao real. `discard_pending_action` rejeita a acao pendente quando o cliente rejeita claramente a operacao.

Somente uma acao pode ficar aguardando confirmacao por `instance + phone`. Uma nova preparacao substitui a anterior marcando-a como `superseded`; acoes antigas sao preservadas. Acoes pendentes expiram conforme `SCHEDULING_CONFIRMATION_TTL_MINUTES`.

Telefone, instancia e `resource_key` sao injetados pelo backend a partir da mensagem recebida e das configuracoes. O modelo nao recebe essas identidades como argumentos de ferramenta, nao acessa SQL e nao executa funcoes Python genericas. PostgreSQL continua sendo a fonte da verdade.

## Dominio da agenda

O dominio da agenda foi implementado em Python e PostgreSQL, mas ainda nao esta conectado ao Carlos, ao prompt ou a chamadas de ferramentas da OpenAI.

Servicos possuem duracao em minutos e preco em centavos. Um agendamento pode conter varios servicos; a duracao total e o preco total sao calculados automaticamente pela aplicacao a partir do catalogo ativo. Dinheiro nao usa `float`.

Horarios de funcionamento precisam ser cadastrados por `instance`, `resource_key` e dia da semana. A agenda padrao usa `resource_key=main`. Nenhum servico e nenhum horario de funcionamento e criado automaticamente.

Datas e horarios publicos da agenda usam a data e hora local da barbearia. O timezone padrao e `America/Sao_Paulo`; antes de salvar ou consultar o banco, a aplicacao converte para UTC. Ao retornar resultados, converte novamente para o timezone da barbearia.

Agendamentos cancelados usam soft delete por `status=cancelled`, com `cancelled_at` e motivo sanitizado. Os snapshots em `appointment_services` preservam nome, duracao e preco usados no momento da criacao; alteracoes futuras no catalogo nao mudam agendamentos antigos.

No PostgreSQL, uma exclusion constraint com `EXCLUDE USING gist` e `tstzrange(start_at, end_at, '[)')` impede sobreposicao entre agendamentos `scheduled` na mesma combinacao `instance` e `resource_key`. O SQLite usado nos testes comuns nao reproduz totalmente essa garantia concorrente; nele a aplicacao faz verificacao explicita sequencial de sobreposicao.

Novas configuracoes:

```env
BARBERSHOP_TIMEZONE=America/Sao_Paulo
DEFAULT_RESOURCE_KEY=main
SCHEDULING_MIN_NOTICE_MINUTES=30
SCHEDULING_MAX_DAYS_AHEAD=90
SCHEDULING_SLOT_INTERVAL_MINUTES=10
SCHEDULING_CONFIRMATION_CODE_LENGTH=8
SCHEDULING_MAX_SERVICES_PER_APPOINTMENT=5
```

## URLs locais

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/health/database
http://127.0.0.1:8000/docs
```

## Teste manual do webhook no PowerShell

```powershell
$body = @{
    event = "messages.upsert"
    instance = "turatti-barbe"
    data = @{
        key = @{
            id = "ABC123"
            remoteJid = "5534999999999@s.whatsapp.net"
            fromMe = $false
        }
        pushName = "Cliente Teste"
        message = @{
            conversation = "Ola, gostaria de marcar um corte amanha."
        }
    }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/webhooks/evolution" `
    -ContentType "application/json" `
    -Body $body
```

## Testes

```powershell
pytest
pytest -W default
```

## Producao com Docker Compose

### Preparacao

```bash
cp .env.production.example .env.production
```

Altere todos os valores `CHANGE_ME` antes de subir a VPS. Nao coloque credenciais reais no repositorio.

### Build e inicializacao

```bash
docker compose --env-file .env.production -f compose.production.yml build
docker compose --env-file .env.production -f compose.production.yml up -d
```

O fluxo esperado e:

```text
PostgreSQL saudavel
    v
migrate executa alembic upgrade head
    v
api, inbound-worker e outbound-worker iniciam
```

### Logs

```bash
docker compose --env-file .env.production -f compose.production.yml logs -f api
docker compose --env-file .env.production -f compose.production.yml logs -f inbound-worker
docker compose --env-file .env.production -f compose.production.yml logs -f outbound-worker
```

### Status

```bash
docker compose --env-file .env.production -f compose.production.yml ps
```

### Migration manual

```bash
docker compose --env-file .env.production -f compose.production.yml run --rm migrate
```

As migrations rodam em container separado. A API nao executa migration, nao cria tabelas e nao inicia workers.

### Diagnostico

```bash
docker compose --env-file .env.production -f compose.production.yml exec api \
  python -m app.cli.queue_status
```

Para JSON:

```bash
docker compose --env-file .env.production -f compose.production.yml exec api \
  python -m app.cli.queue_status --json
```

O diagnostico mostra contagens e datas tecnicas das filas, sem telefone, texto, nome, transcricao ou conteudo de midia.

### Backup

Execute backup antes de migrations e antes de atualizacoes:

```bash
BACKUP_DIR=/var/backups/agente_barbearia ./scripts/backup_postgres.sh
```

Defina retencao fora da aplicacao. Teste restore periodicamente. Armazene copias seguras fora da VPS. Backups nao devem ser enviados ao repositorio.

### Restore

Pare os containers de aplicacao antes do restore:

```bash
docker compose --env-file .env.production -f compose.production.yml stop api inbound-worker outbound-worker
./scripts/restore_postgres.sh /caminho/do/backup.dump
docker compose --env-file .env.production -f compose.production.yml up -d api inbound-worker outbound-worker
```

Restaure primeiro em ambiente de teste sempre que possivel. O script exige confirmacao explicita, salvo `CONFIRM_RESTORE=yes`.

### Atualizacao

Fluxo recomendado:

```text
backup
build
migration
restart controlado
readiness
verificacao das filas
```

O script `scripts/deploy.sh` executa esse fluxo sem `git pull`, sem apagar volumes e sem sobrescrever `.env.production`.

### Reverse proxy

HTTPS deve ser terminado pelo EasyPanel, Nginx, Traefik ou Cloudflare ja existente. Esta etapa nao instala nem configura reverse proxy. Somente a API deve ser exposta pelo proxy; PostgreSQL e workers permanecem internos.

### Webhook

A URL publica deve apontar para o endpoint:

```text
POST /webhooks/evolution
```

Opcionalmente habilite header secreto:

```env
EVOLUTION_WEBHOOK_AUTH_ENABLED=true
EVOLUTION_WEBHOOK_SECRET=CHANGE_ME
EVOLUTION_WEBHOOK_SECRET_HEADER=x-webhook-secret
```

Configure o mesmo header na Evolution API. Nao exponha workers nem PostgreSQL.

### Área do barbeiro / Dashboard administrativo

O dashboard administrativo tem páginas separadas. A visão geral fica em:

```text
GET /admin/dashboard
```

Ele vem desativado por padrao. Para ativar manualmente na VPS, configure:

```env
ADMIN_DASHBOARD_ENABLED=true
ADMIN_DASHBOARD_USERNAME=admin
ADMIN_DASHBOARD_PASSWORD=troque_essa_senha
```

Use senha forte e não salve no Git. Em produção, não exponha sem HTTPS.

Todas as rotas `/admin/*` usam HTTP Basic Auth. Quando `ADMIN_DASHBOARD_ENABLED=false`, elas retornam 404. Quando habilitado, usuario e senha sao obrigatorios; nao existe usuario fixo no codigo nem senha padrao.

Páginas disponíveis:

```text
/admin/dashboard       Visão geral
/admin/agenda          Agenda do dia com filtros
/admin/servicos        Ranking e catálogo de serviços
/admin/faturamento     Estimativas de faturamento
/admin/clientes        Clientes com telefone mascarado
/admin/horarios        Horários e dias movimentados
/admin/cancelamentos   Cancelamentos e no-shows
/admin/configuracoes   Dados cadastrados da barbearia
```

Esta versão é somente leitura. Alterações de agenda ainda devem ser feitas pelo fluxo do WhatsApp ou diretamente no banco apenas em emergência operacional.

Métricas disponíveis: agenda de hoje, volume de agendamentos, comparação com mês anterior, faturamento estimado, clientes únicos, clientes recorrentes, cancelamentos, no-show, ocupação estimada, serviços mais e menos agendados e horários mais movimentados.

Limitações: o faturamento é estimado a partir dos valores dos agendamentos e o dashboard não valida pagamentos recebidos. Serviços com preço "a partir de" continuam sendo estimativas. Telefones aparecem mascarados por padrão. Não exponha essa área publicamente sem senha forte.

### Testes PostgreSQL opcionais

A suite padrao usa SQLite e nao exige Docker. Para testes com PostgreSQL real:

```bash
docker compose -f compose.test.yml up -d
TEST_POSTGRES_DATABASE_URL=postgresql+asyncpg://agente_barbearia_test:agente_barbearia_test_password@127.0.0.1:55432/agente_barbearia_test pytest -m postgres
docker compose -f compose.test.yml down -v
```
