# 🎧 Live Sync — Desafio de Observabilidade B3

Solução do **Cenário 1 — Mainstage Live Sync**: uma API instrumentada com OpenTelemetry, com métricas, logs e traces visualizados no Grafana.

---

## 📑 Sumário

* [Visão geral](#-visão-geral)
* [Como rodar](#-como-rodar)
* [API](#-api)
* [Requisitos do desafio](#-requisitos-do-desafio)
  * [1. Observabilidade e instrumentação](#-1-observabilidade-e-instrumentação)
  * [2. Dashboards e visualização](#️-2-dashboards-e-visualização)
  * [3. Funcionamento da API e resiliência](#️-3-funcionamento-da-api-e-resiliência)
  * [4. Documentação e infraestrutura](#-4-documentação-e-infraestrutura)
* [Estrutura do repositório](#️-estrutura-do-repositório)
* [Decisões de projeto](#-decisões-de-projeto)

---

## 🔭 Visão geral

**O problema:**
Num festival, os painéis de LED e a pirotecnia precisam acompanhar a música que está tocando. A **live-sync** é a API que faz essa ponte: recebe a faixa atual (`artist` e `title`), consulta uma base musical externa para obter o BPM e devolve as instruções de palco: nível de energia, preset visual e o tempo gasto na consulta (`sync_delay_ms`). A base externa é instável, como a rede de um festival: às vezes falha, às vezes demora.

**O objetivo:**
Tornar esse comportamento **observável** e garantir que a API continue de pé quando a dependência cai:

* **Métricas:** quantas requisições chegam, quantas falham e quanto demoram.
* **Logs:** por que cada requisição falhou.
* **Traces:** por onde cada requisição passou.

![Arquitetura](/assets/architecture.svg)

| Componente | Função |
| :--- | :--- |
| `api` (live-sync) | A API do desafio, em Flask. Chama o catálogo com timeout de 2 s e transforma qualquer falha dele em 503. |
| `music-catalog` | Simula a API externa de streaming: devolve o BPM das faixas, com falhas (5%) e lentidão (2%) configuráveis. |
| OpenTelemetry | Instrumenta os dois serviços sem alterar o código das rotas: cria os traces, propaga o contexto entre eles e envia logs e traces ao Collector. |
| `lgtm` (`grafana/otel-lgtm`) | A stack de observabilidade num só container. |
| ↳ OTel Collector | Recebe a telemetria via OTLP e distribui para os bancos. |
| ↳ Prometheus | Guarda as métricas, buscadas em `/metrics` de cada serviço. |
| ↳ Loki | Guarda os logs. |
| ↳ Tempo | Guarda os traces. |
| ↳ Grafana | Exibe o dashboard e permite consultar e cruzar os três sinais: de um log para o trace pelo `trace_id`. |
| `k6-load-test` (`grafana/k6`) | Gera tráfego (50 usuários virtuais por 5 minutos) para popular o dashboard. |

---

## 🚀 Como rodar

**Pré-requisito:** Docker com Compose v2.

```bash
docker compose up --build -d
```

Sobem a stack de observabilidade (`lgtm`), o catálogo simulado, a API e o k6, que gera carga por 5 minutos (50 usuários virtuais). Os gráficos do dashboard começam a mostrar dados em menos de um minuto.

| Acesso | Endereço |
| :--- | :--- |
| Dashboard (Grafana, sem login) | <http://localhost:3000> |
| API | <http://localhost:8080/live-sync/track?artist=Foo%20Fighters&title=Everlong> |
| Métricas (Prometheus) | <http://localhost:8080/metrics> |

* **Rodar a carga de novo:** `docker compose run --rm k6-load-test`
* **Parar:** `docker compose down` (com `-v`, apaga também os dados da stack)

---

## 🎵 API

`GET /live-sync/track?artist={artist}&title={title}`

**Resposta esperada:**

```json
{
  "track": "Everlong",
  "artist": "Foo Fighters",
  "bpm": 158,
  "energy_level": "High",
  "visual_preset": "strobes_and_lasers",
  "sync_delay_ms": 45
}
```

| Status | Quando |
| :--- | :--- |
| 200 | Faixa encontrada |
| 400 | `artist` ou `title` ausente ([exemplo](http://localhost:8080/live-sync/track?artist=Avicii)) |
| 404 | Faixa fora do catálogo ([exemplo](http://localhost:8080/live-sync/track?artist=foo&title=bar)) |
| 503 | Catálogo com erro, sem resposta em 2 s ou fora do ar |
| 500 | Erro inesperado no próprio código (bug) |

O catálogo simulado tem três faixas, uma por nível de energia; qualquer outra retorna 404:

| Faixa | BPM | `energy_level` | `visual_preset` |
| :--- | :--- | :--- | :--- |
| [Teardrop](http://localhost:8080/live-sync/track?artist=Massive%20Attack&title=Teardrop) (Massive Attack) | 77 | `Low` | `haze_and_spotlights` |
| [Levels](http://localhost:8080/live-sync/track?artist=Avicii&title=Levels) (Avicii) | 126 | `Medium` | `beams_and_color_sweeps` |
| [Everlong](http://localhost:8080/live-sync/track?artist=Foo%20Fighters&title=Everlong) (Foo Fighters) | 158 | `High` | `strobes_and_lasers` |

---

## ✅ Requisitos do desafio

Como cada item do sistema de pontuação é atendido e como verificar.

### 📈 1. Observabilidade e instrumentação

**Métricas RED no formato Prometheus**

Cada serviço expõe `GET /metrics` (`prom_metrics.py`), coletado pelo Prometheus da `lgtm` a cada 5 s (`prometheus.yaml`):

| RED | Métrica |
| :--- | :--- |
| Rate | `http_requests_total` (contador, por `method`, `route` e `status`) |
| Errors | `http_requests_total{status=~"5.."}` |
| Duration | `http_request_duration_seconds` (histograma, por `method` e `route`) |

> **Verificar:** <http://localhost:8080/metrics>

<details>
<summary><b>Como ler o histograma de duração</b></summary>

O histograma não guarda a duração de cada requisição: guarda contadores por faixa de tempo (*buckets*). Cada linha `_bucket{le="X"}` conta quantas requisições levaram **até** X segundos (`le` = *less or equal*), então os valores são cumulativos. Além das faixas, há `_count` (total de requisições) e `_sum` (soma de todas as durações).

Com isso, o Prometheus calcula:

* **Média:** `_sum ÷ _count`.
* **Percentis (p95, p99):** `histogram_quantile` encontra a faixa em que o percentil cai e interpola dentro dela. É uma estimativa, limitada à precisão das faixas.

Guardar faixas em vez de cada valor mantém o custo fixo, independentemente do volume de requisições. O histograma não tem o label `status`, para não multiplicar o número de séries.

</details>

**Logs em JSON**

Os dois serviços usam o mesmo formatter (`json_logging.py`): uma linha JSON por evento no stdout, também enviada ao Loki via OTLP. Exemplo, formatado em várias linhas para facilitar a leitura:

```json
{
  "timestamp": "2026-10-11T20:59:48.259+00:00",
  "level": "WARNING",
  "service": "live-sync",
  "logger": "app",
  "message": "music catalog unavailable",
  "trace_id": "de2468bc4b084303bee476b6348ca8ef",
  "span_id": "26bb475dfcdb6312",
  "dependency": "music-catalog",
  "reason": "timeout",
  "http_status": 503
}
```

* **Campos sempre presentes:** `timestamp`, `level`, `service`, `logger` e `message`. O `service` diz de onde veio o log: `live-sync` ou `music-catalog`.
* **Durante uma requisição:** também `trace_id` e `span_id`.
* **Campos adicionais:** variam conforme o evento.

O nível segue o resultado da requisição no serviço que registra o log:

* **`INFO`:** deu certo, ou é um evento informativo.
* **`WARNING`:** falha prevista e tratada, que vira 503. O motivo vai no campo `reason`: `timeout`, `connection error` ou `unexpected status <código>`.
* **`ERROR`:** exceção não tratada, que vira 500, com o traceback.

> **Verificar:** `docker compose logs --no-log-prefix api` ou, no Grafana, **Explore → Loki** com `{service_name="live-sync"}`.

<details>
<summary><b>Todos os logs de cada serviço</b></summary>

| Serviço | Nível | `message` | Quando | Status HTTP | Campos adicionais |
| :--- | :--- | :--- | :--- | :--- | :--- |
| live-sync | `INFO` | `live-sync configured` | Ao iniciar | — | `music_catalog_url`, `music_catalog_timeout_s` |
| live-sync | `WARNING` | `music catalog unavailable` | O catálogo falhou, demorou mais de 2 s ou está fora do ar | 503 | `dependency`, `http_status` e `reason` |
| live-sync | `ERROR` | `Exception on /live-sync/track [GET]` | Bug no código da API | 500 | `exception` (traceback) |
| music-catalog | `INFO` | `music-catalog configured` | Ao iniciar | — | `failure_rate`, `latency_min_ms`, `latency_max_ms`, `slow_rate`, `slow_min_ms`, `slow_max_ms` |
| music-catalog | `INFO` | `simulated slow response` | Sorteada uma resposta lenta | 200 | `delay_ms` |
| music-catalog | `WARNING` | `simulated failure` | Sorteada uma falha | 503 | `reason`, `http_status` |
| music-catalog | `ERROR` | `Exception on /track [GET]` | Bug no código do catálogo | 500 | `exception` (traceback) |

Respostas 200 comuns não geram log: as métricas já as contam.

Uma resposta lenta é `INFO` no catálogo porque, para ele, a requisição deu certo: ele responde 200, só que tarde. Se passar de 2 s, quem sofre o timeout é a live-sync, e é ela que registra o `WARNING`. Seguindo o `trace_id` de um timeout, o `delay_ms` no log do catálogo explica a desistência.

</details>

**`trace_id` nos logs**

O formatter lê o span ativo do OpenTelemetry e adiciona `trace_id` e `span_id` a cada log escrito durante uma requisição. A instrumentação automática (Flask e `requests`) propaga o contexto entre a API e o catálogo pelo cabeçalho `traceparent`, então os logs dos dois serviços para a mesma requisição têm o **mesmo** `trace_id`; o `span_id` é diferente em cada um, porque cada serviço tem seu próprio span.

> **Verificar:** no Loki, abra um log e clique no `trace_id`. O trace abre no Tempo com três spans: a requisição na API, a chamada ao catálogo e o catálogo atendendo. No sentido contrário, o botão **Related logs** de um span no Tempo mostra os logs daquela requisição.

---

### 🖥️ 2. Dashboards e visualização

**Dashboard exportado em JSON**

O `dashboard.json`, na raiz, é provisionado automaticamente (`grafana-dashboards.yaml`) e abre como página inicial do Grafana em <http://localhost:3000>.

**Painéis**

Cada painel tem uma linha por serviço (`live-sync` e `music-catalog`). Valores medidos com a configuração padrão e o k6 rodando:

| Painel | O que mostra | Medido |
| :--- | :--- | :--- |
| Requisições por segundo | Requisições recebidas por segundo, por serviço | ~270 req/s, com as duas linhas sobrepostas |
| Taxa de erros (5xx) | Porcentagem de respostas 5xx sobre o total | live-sync ~6%, catálogo ~5% |
| Latência: p95 e média | O tempo abaixo do qual estão 95% das requisições, e o tempo médio | p95: live-sync ~95 ms, catálogo ~50 ms. Média: live-sync ~75 ms, catálogo ~70 ms |
| Latência: p99 (cauda) | O tempo abaixo do qual estão 99% das requisições | ~2 s nos dois serviços |

![Dashboard com a configuração padrão e o k6 rodando](/assets/dashboard.jpg)

Dois painéis têm uma linha tracejada de referência:

* **10% no painel de erros:** o limite a partir do qual a taxa de erros deixa de ser o ruído esperado e passa a indicar um problema.
* **2 s no painel de p99:** o timeout da live-sync para o catálogo. Se o p99 encosta nessa linha, as requisições mais lentas estão sendo cortadas pelo timeout, e cada uma virou um 503.

<details>
<summary><b>Resumo do k6</b></summary>

O resumo do k6, ao fim dos 5 minutos, mostra os mesmos números vistos pelo cliente: 269 req/s, 5,87% de falhas, latência média de 84,5 ms, mediana de 49,1 ms e p95 de 93,1 ms.

![Resumo do k6 ao fim do teste de carga](/assets/k6-summary.jpg)

</details>

<details>
<summary><b>De onde vem cada número</b></summary>

Os valores saem destes parâmetros:

* **Catálogo:** latência normal de 10 a 50 ms (média de 30 ms), 5% de falhas e 2% de respostas lentas, de 1 a 3 s.
* **live-sync:** desiste do catálogo depois de 2 s (timeout) e responde 503.
* **k6:** 50 usuários virtuais. Cada um faz uma requisição, espera a resposta e mais 100 ms, e repete. Assim, **RPS = 50 ÷ (0,1 s + latência média)**: quanto mais lenta a API, menos requisições por segundo.

| Painel | Cálculo |
| :--- | :--- |
| Requisições por segundo | A latência média vista pelo k6 é ~85 ms, então 50 ÷ (0,1 + 0,085) ≈ 270. As linhas se sobrepõem porque cada requisição à API gera exatamente uma ao catálogo. |
| Taxa de erros (5xx) | O catálogo responde 503 em 5% das chamadas. A live-sync repassa esses 5% e soma os timeouts: das 2% de chamadas lentas (1 a 3 s), metade passa de 2 s. São mais 1%, total de 6%. Nos timeouts, o catálogo termina com 200, por isso a taxa dele fica em 5%. |
| Latência: p95 e média | **Média:** ~45 ms nas chamadas normais, mais 2% de chamadas de até 2 s: 0,98 × 45 ms + 0,02 × ~1,75 s ≈ 80 ms (o k6 mediu 84,5 ms; o painel, que mede dentro da API, ~75 ms). **p95:** as lentas são só 2%, então o p95 cai entre as chamadas normais. |
| Latência: p99 (cauda) | 98% das chamadas são normais, então o p99 cai no meio das lentas, que vão de 1 a 3 s: ~2 s. Na live-sync, o timeout também corta tudo em 2 s. |

</details>

<details>
<summary><b>Por que 10% e 2 s</b></summary>

* **10%:** com a configuração padrão, a live-sync fica em ~6%. Com ~270 req/s, cada ponto do gráfico resume milhares de requisições, então a taxa quase não oscila em volta desses 6%. Um limite de 10% fica com folga acima do normal, sem alarme falso, e baixo o bastante para que uma degradação real o cruze. Num sistema real, esse valor viria do SLO (por exemplo, 99,9% de disponibilidade); aqui ele é calibrado pelo ruído do catálogo simulado.
* **2 s:** uma chamada normal leva menos de 100 ms. Com 2 s, há uma folga de 20 vezes para variações normais de rede sem descartar respostas válidas, e o palco não fica esperando indefinidamente por uma dependência travada. Um timeout curto também protege a capacidade da API: cada requisição esperando ocupa uma das 32 threads do Gunicorn. As respostas lentas simuladas (1 a 3 s) ficam dos dois lados do limite, então metade delas sofre timeout, o que torna o comportamento visível no dashboard.

</details>

<details>
<summary><b>Como comparar live-sync e music-catalog</b></summary>

A latência da live-sync **inclui** a do catálogo: a requisição só termina depois que a chamada ao catálogo termina. Um trace típico mostra a divisão:

| Span | Duração | O que é |
| :--- | :--- | :--- |
| `live-sync GET /live-sync/track` | 68 ms | A requisição inteira, vista pela API |
| `GET` (chamada ao catálogo) | 65 ms | Da API mandando a requisição até receber a resposta |
| `music-catalog GET /track` | 49 ms | O catálogo trabalhando |

Ou seja, ~16 ms ficam na chamada pela rede e ~3 ms no processamento da API. Daí a relação entre as linhas de cada painel:

* **p95, live-sync acima:** o catálogo leva de 10 a 50 ms nas chamadas normais, então o p95 dele fica em ~50 ms. A live-sync soma o custo da chamada.
* **p99, praticamente iguais:** a cauda é formada pelas mesmas chamadas lentas do catálogo. Perto de 2 s, o custo da chamada é desprezível, e o timeout limita a live-sync a 2 s.
* **Média do catálogo maior que o p95 dele:** a média é sensível a valores extremos. Os 2% de chamadas lentas respondem por mais da metade dela: 0,98 × 30 ms + 0,02 × 2 s ≈ 69 ms. O p95 mostra a experiência típica; a média denuncia que existe uma cauda pesada.
* **Médias próximas:** dois efeitos se compensam. A live-sync soma o custo da chamada a toda requisição, mas o timeout corta as chamadas lentas em 2 s, enquanto o catálogo conta a lentidão inteira, de até 3 s.
* **Painel (~75 ms) contra k6 (~85 ms):** o painel mede dentro da API, do início ao fim da rota. O k6 mede de fora e inclui a rede e a espera até o Gunicorn atender. Métricas do servidor sempre mostram um pouco menos do que o cliente sente.

**Para diagnóstico:** se as duas linhas sobem juntas, o problema está no catálogo. Se só a live-sync sobe, o problema está na própria API ou na rede entre os dois.

</details>

---

### ⚙️ 3. Funcionamento da API e resiliência

**Respostas em JSON**

Ver [API](#-api).

**Sem crash quando a API externa falha**

A chamada ao catálogo tem timeout de 2 s. Erro, timeout ou falha de conexão são tratados: a API responde 503, registra o motivo no log e continua atendendo. O catálogo simulado já falha em ~5% das chamadas e demora de 1 a 3 s em ~2%, então parte das requisições normais termina em 503.

**Provocando falhas**

Com o projeto rodando (ver [Como rodar](#-como-rodar)), use os comandos abaixo. Eles usam a sintaxe do bash (Linux, macOS ou WSL):

| Cenário | Comando | O que se vê no dashboard |
| :--- | :--- | :--- |
| 50% de erros no catálogo | `FAILURE_RATE=0.5 docker compose up -d --wait music-catalog` | Erros sobem para ~50% nos dois serviços, acima da linha de 10%. Latência e RPS não mudam, porque a falha acontece depois da latência normal. |
| 50% de respostas lentas | `SLOW_RATE=0.5 docker compose up -d --wait music-catalog` | Erros sobem só na live-sync, por causa dos timeouts; o catálogo fica em ~5%, porque termina as chamadas lentas com 200. A latência sobe e o RPS cai. |
| Catálogo fora do ar | `docker compose stop music-catalog` | Erros da live-sync vão a 100%. A linha do catálogo some, porque o Prometheus não consegue mais coletar as métricas dele. A latência da live-sync sobe para 2 a 3 s (ver abaixo). |
| Voltar ao normal | `docker compose up -d --wait music-catalog` | Tudo volta aos valores medidos com a configuração padrão. |

Os comandos só mudam o comportamento do catálogo; para ver o efeito, é preciso gerar requisições. Há duas formas, e elas podem rodar ao mesmo tempo:

* **No dashboard:** com o k6 rodando. Se a carga inicial já terminou, rode `docker compose run --rm k6-load-test` em outro terminal.
* **No terminal:** o loop abaixo faz 100 requisições e conta os status. Não depende do k6.

```bash
for i in $(seq 1 100); do
  curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8080/live-sync/track?artist=Avicii&title=Levels"
done | sort | uniq -c
```

<details>
<summary><b>Por que o catálogo fora do ar deixa a live-sync lenta</b></summary>

Com o container parado, o nome `music-catalog` some do DNS do Docker, e cada requisição espera de 2 a 3 s até a resolução do nome falhar. O timeout de 2 s do `requests` não cobre essa etapa. A falha aparece no log com `reason`: `connection error`.

</details>

<details>
<summary><b>Erro 500 e logs <code>ERROR</code></b></summary>

Nenhum dos cenários acima gera `ERROR`: em todos, a live-sync trata a falha e registra `WARNING`. Ela só registraria `ERROR` diante de um bug no próprio código, e provocar isso exigiria código feito só para a demonstração.

O `ERROR` pode ser visto no `music-catalog`. Para isso, edite no `docker-compose.yaml` o `SLOW_MIN_MS` e o `SLOW_MAX_MS` para valores negativos (`-1000` e `-500`) e rode `SLOW_RATE=1 docker compose up -d --wait music-catalog`. Com atraso negativo, o `time.sleep()` do catálogo lança uma exceção não tratada:

* **`music-catalog`:** responde 500 e registra `ERROR` com o traceback.
* **`live-sync`:** recebe o 500, responde 503 e registra `WARNING` com `reason`: `unexpected status 500`.

Cada serviço classifica a falha do seu ponto de vista: para o catálogo é um bug; para a API, uma dependência que falhou. Para voltar ao normal, desfaça a edição e rode `docker compose up -d --wait music-catalog`.

</details>

---

### 📦 4. Documentação e infraestrutura

**Dockerfile otimizado** (`live-sync/Dockerfile` e `music-catalog/Dockerfile`)

* Imagem base `python:3.14-slim`.
* Dependências instaladas antes de copiar o código, para reaproveitar o cache de camadas.
* Execução com usuário sem privilégios.
* Gunicorn com o agente do OpenTelemetry (`opentelemetry-instrument`).

**Orquestração** (`docker-compose.yaml`)

Um único comando sobe a API, o catálogo, a `lgtm` (Collector, Prometheus, Loki, Tempo e Grafana) e o k6. Healthchecks garantem a ordem de subida (`lgtm` → catálogo → API → k6), e as versões das imagens são fixas.

---

## 🗂️ Estrutura do repositório

```
.
├── README.md
├── docker-compose.yaml        # orquestração dos quatro serviços
├── load.js                    # teste de carga do k6
├── dashboard.json             # dashboard do Grafana
├── grafana-dashboards.yaml    # provisionamento do dashboard
├── prometheus.yaml            # configuração do Prometheus da lgtm, com a coleta de /metrics
├── assets/                    # imagens do README
│   ├── architecture.svg
│   ├── dashboard.jpg
│   └── k6-summary.jpg
├── live-sync/                 # a API
│   ├── app.py                 # rotas e chamada ao catálogo
│   ├── json_logging.py        # logs em JSON com trace_id
│   ├── prom_metrics.py        # métricas RED e rota /metrics
│   ├── requirements.txt
│   └── Dockerfile
└── music-catalog/             # API externa simulada
    ├── app.py                 # catálogo, falhas e lentidão simuladas
    ├── json_logging.py
    ├── prom_metrics.py
    ├── requirements.txt
    └── Dockerfile
```

---

## 🧠 Decisões de projeto

<details>
<summary><b>Flask</b></summary>

É síncrono e simples, e casa com o `requests` usado para chamar o catálogo. A instrumentação automática do OpenTelemetry para os dois é madura e não exige mudar o código das rotas. O ganho de desempenho do FastAPI (assíncrono) não é necessário nessa escala.

</details>

<details>
<summary><b>Gunicorn, com 1 processo e 32 threads</b></summary>

O servidor embutido do Flask é só para desenvolvimento e não foi feito para carga. O Gunicorn é um servidor WSGI de produção e atende várias requisições em paralelo.

* **Threads em vez de vários processos.** O normal seria subir vários processos (*workers*), mas aqui isso quebraria a telemetria:
  * cada processo teria seus próprios contadores, e o Prometheus, a cada coleta do `/metrics`, leria os de um processo diferente, com números inconsistentes;
  * o OpenTelemetry é inicializado antes de o Gunicorn criar os processos, e as threads que enviam a telemetria não sobrevivem a essa cópia (*fork*).

  Com um processo só, há um único conjunto de métricas e um único exportador.
* **Threads servem bem a este caso.** A API passa a maior parte do tempo esperando o catálogo, e enquanto uma thread espera pela rede, as outras rodam.
* **Por que 32.** O número de requisições em andamento ao mesmo tempo é a vazão vezes a latência: 270 req/s × 0,085 s ≈ 23. 32 threads cobrem isso com folga. Quando a latência sobe (catálogo lento ou fora do ar), as threads se esgotam e as requisições passam a esperar na fila. É mais um motivo para o timeout ser curto.

</details>

<details>
<summary><b>Dois serviços separados</b></summary>

A API externa simulada roda em seu próprio container, em vez de ser uma função dentro da API. Assim a chamada atravessa a rede de verdade, e isso permite:

* ter um trace distribuído entre dois serviços, com o contexto propagado pelo cabeçalho `traceparent`;
* reproduzir falhas reais de dependência: timeout, falha de conexão, container fora do ar;
* ter métricas e logs separados para a API e para a dependência.

</details>

<details>
<summary><b>503 para falhas previstas, 500 para imprevistas</b></summary>

A distinção diz se o problema está numa dependência ou no próprio código:

* **503** (*Service Unavailable*) indica indisponibilidade temporária: quem chama pode tentar de novo.
* **500** indica um bug no código.
* A mesma regra vale nos logs (`WARNING` × `ERROR`) e nas métricas (o `status` do `http_requests_total`).

</details>

<details>
<summary><b>400 e 404</b></summary>

São erros de quem chama, não falhas do serviço. Separá-los dos 5xx evita que entradas inválidas inflem a taxa de erros do dashboard:

* O **400** é validado antes de chamar o catálogo, sem gastar uma chamada externa.
* O **404** é uma resposta válida: a faixa não existe no catálogo.

</details>

<details>
<summary><b>Docker Compose em vez de Swarm</b></summary>

O projeto roda numa única máquina local, que é o caso de uso do Compose. O Swarm é para clusters e complicaria a execução sem ganho:

* exige `docker swarm init`;
* não constrói imagens (`build`), então seria preciso publicá-las num registry;
* ignora o `depends_on` com healthcheck, que garante a ordem de subida;
* trata serviços como réplicas permanentes, o que não combina com o k6, que roda uma vez e termina.

</details>