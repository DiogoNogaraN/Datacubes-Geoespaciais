# Sentinel-2 Vegetation Indices Pipeline

Pipeline automatizado para download, processamento e montagem de datacubes de índices de vegetação Sentinel-2, com suavização temporal via HANTS e extração de variáveis topográficas. O resultado é um datacube NumPy pronto para análises de aprendizado de máquina aplicadas à agricultura de precisão.

---

## Visão Geral

O pipeline é dividido em quatro módulos sequenciais, orquestrados por um container Docker:

| Módulo | Script | Descrição |
|--------|--------|-----------|
| 0 | `0-topografia.py` | Download do DEM Copernicus, reamostragem para 10 m e cálculo de variáveis topográficas (altitude, declividade, SWI, orientação N/L) via GDAL + pysheds |
| 1 | `1-download_sentinel2.py` | Download das imagens Sentinel-2 via OpenEO (Copernicus Data Space), com seleção de índices, controle de cobertura de nuvens e suporte a frequência mensal ou semanal |
| 2 | `2-HANTS.py` | Recorte pela área de interesse, suavização da série temporal com o algoritmo HANTS e reprojeção para o SRC do projeto |
| 3 | `3-datacube.py` | Montagem dos datacubes NumPy normalizados: `IV_norm01.npy` (índices × tempo × pixels) e `Estatico_norm01.npy` (variáveis topográficas) |

---

## Índices de Vegetação Suportados

NDVI, NDRE, GNDVI, GOSAVI, MCARI, MCARI1, LNC, NDWI1, NDWI2

---

## Pré-requisitos

- [Docker](https://www.docker.com/) instalado
- Conta no [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) (gratuita)
- Shapefile da área de interesse (`.shp` + arquivos auxiliares)

---

## Instalação

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/DownloadSentinel2Indices.git
cd DownloadSentinel2Indices
```

### 2. Criar a estrutura de pastas no HD

**Windows:**
```bat
.\setup_cliente.bat D Nome_Cliente fazenda
```

**Linux/macOS:**
```bash
./setup_cliente.sh /mnt/hd/SEU_HD Nome_Cliente
```

Isso cria a seguinte estrutura:
```
SEU_HD/
  clientes/
    Nome_Cliente/
      inputs/          ← colocar o shapefile aqui
      TOPOGRAFIA/      ← gerado pelo Módulo 0
      HANTS/           ← gerado pelo Módulo 2
      HANTS_REPROJETADO/
      DATACUBE/        ← datacubes finais
```

### 3. Copiar o shapefile

Copie o `.shp` e todos os arquivos auxiliares (`.dbf`, `.prj`, `.shx`) para a pasta `inputs/` do cliente.

### 4. Construir a imagem Docker

```bash
docker build -t sentinel2-pipeline .
```

---

## Uso

### Processar uma única área

```bash
docker run --rm \
  -v "D:\SEU_HD:/dados" \
  -e CLIENTE_NOME=Nome_Cliente \
  -e SHP_FILENAME=fazenda.shp \
  -e SRC_PROJETO=EPSG:32722 \
  -e FREQUENCIA=mensal \
  -e DATA_INICIO=2022-01-01 \
  -e DATA_FIM=2024-12-31 \
  -e COPERNICUS_USER=seu_email@email.com \
  -e COPERNICUS_PASS=sua_senha \
  sentinel2-pipeline
```

### Processar múltiplas áreas em lote

Configure o arquivo `areas_lote.json` (veja exemplo no repositório) e execute:

**Windows:**
```bat
.\processar_areas.bat areas_lote.json
```

**Linux/macOS:**
```bash
./processar_areas.sh areas_lote.json /mnt/hd/SEU_HD
```

---

## Variáveis de Ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `CLIENTE_NOME` | Sim | Nome do cliente/pasta no HD |
| `SHP_FILENAME` | Não | Nome do shapefile (padrão: `contorno_fazenda.shp`) |
| `SRC_PROJETO` | Não | EPSG do CRS alvo (padrão: `EPSG:32722`) |
| `FREQUENCIA` | Não | `mensal` ou `semanal` (padrão: `mensal`) |
| `MESES_SAFRA` | Não | Meses de interesse, separados por vírgula (ex: `10,11,12,1`). Vazio = ano todo |
| `DATA_INICIO` | Não | Data de início (padrão: `2022-01-01`) |
| `DATA_FIM` | Não | Data de fim (padrão: `2025-12-31`) |
| `COPERNICUS_USER` | Sim | E-mail da conta Copernicus Data Space |
| `COPERNICUS_PASS` | Sim | Senha da conta Copernicus Data Space |
| `PARAR_APOS_MODULO` | Não | Para o pipeline após o módulo indicado (0–3), útil para auditoria |
| `COMECAR_DO_MODULO` | Não | Pula módulos anteriores ao indicado (0–3), útil para re-runs parciais |

---

## Formato dos Datacubes de Saída

**`IV_{nome}_norm01.npy`** — Shape `(T, H, W, F)`
- `T`: períodos temporais
- `H`, `W`: altura e largura em pixels
- `F`: número de índices de vegetação
- Normalização Min-Max por imagem `[0.0, 1.0]`. Pixels fora da área de interesse = `NaN`.

**`Estatico_{nome}_norm01.npy`** — Shape `(V, H, W)`
- `V`: variáveis topográficas (altitude, declividade, SWI, orientação N/L)
- Normalização Min-Max por variável `[0.0, 1.0]`

---

## Ferramentas de Auditoria

O repositório inclui scripts de inspeção para verificar a qualidade dos outputs em cada etapa:

- `auditoria_modulo1.py` — quicklooks pós-download (cobertura de nuvens, datas, bandas)
- `auditoria_modulo2.py` — inspeção da suavização HANTS (antes/depois por índice)
- `auditoria_modulo3.py` — validação do datacube final (shape, NaNs, distribuição de valores)
- `app_inspecao.py` — aplicação Streamlit interativa para visualização dos datacubes
- `diagnostico_hants.py` — diagnóstico detalhado do pipeline HANTS para identificar falhas

---

## Configuração Avançada (config.json)

O arquivo `config.json` centraliza todos os parâmetros do pipeline e é atualizado automaticamente pelo `entrypoint.sh` com as variáveis de ambiente passadas ao container. Os hiperparâmetros do HANTS por índice (limites de valor, grau de overdetermination, `delta`) podem ser ajustados diretamente neste arquivo conforme a cultura e a região de interesse.

---

## Dependências Principais

- [openeo](https://openeo.org/) — acesso ao Copernicus Data Space
- [rasterio](https://rasterio.readthedocs.io/) — leitura e escrita de rasters
- [geopandas](https://geopandas.org/) — manipulação de shapefiles
- [pysheds](https://github.com/mdbartos/pysheds) — análise de bacia hidrográfica (SWI)
- [hants](https://github.com/gespinoza/hants) — suavização de séries temporais (integrado via Docker)

---

## Licença

Este projeto está disponível sob a licença MIT.
