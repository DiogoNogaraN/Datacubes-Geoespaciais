#!/bin/bash
# =============================================================================
# executar_pipeline.sh -- Orquestrador do Pipeline
#
# Sequencia de execucao:
#   aplicar_patches  -> prepara o HANTS para Python 3
#   verificar_shp    -> confirma/reprojeta shapefile para o CRS do projeto
#   0-topografia     -> download DEM Copernicus + reamostragem + reprojecao + QGIS
#   1-download       -> download Sentinel-2 via OpenEO
#   2-HANTS          -> recorte, suavizacao HANTS e reprojecao
#   3-datacube       -> montagem dos datacubes IV e topografico
#
# Variaveis de controlo:
#   COMECAR_DO_MODULO  Salta modulos anteriores ao indicado (util para re-runs):
#     0 = comecar da topografia (padrao)
#     1 = comecar do download   (salta topografia)
#     2 = comecar do HANTS      (salta topografia + download)
#     3 = comecar do datacube   (salta tudo ate ao datacube)
#
#   PARAR_APOS_MODULO  Para apos o modulo indicado para permitir auditoria:
#     0 = so topografia
#     1 = topografia + download
#     2 = topografia + download + HANTS      (util para ajustar hiperparametros)
#     3 = todos (padrao, equivale a nao definir)
#
# Exemplos:
#   Correr so o Modulo 2 (HANTS):
#     -e COMECAR_DO_MODULO=2 -e PARAR_APOS_MODULO=2
#   Correr so o Modulo 3 (datacube):
#     -e COMECAR_DO_MODULO=3
#
# Auditorias (geradas automaticamente em PREVIEWS/ dentro da pasta do cliente):
#   Modulo 1 -> quicklooks dos indices descarregados
#   Modulo 2 -> series temporais bruto vs HANTS por indice
#   Modulo 3 -> mapa medio e estatisticas do datacube
# =============================================================================

set -e

WORKDIR="/app"
CONFIG="$WORKDIR/config.json"

if [ ! -f "$CONFIG" ]; then
    echo "[ERRO CRITICO] config.json nao encontrado em $WORKDIR. A abortar."
    exit 1
fi

# Ler PARAR_APOS_MODULO e COMECAR_DO_MODULO
PARAR=${PARAR_APOS_MODULO:-$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('_parar_apos_modulo','3'))" 2>/dev/null || echo "3")}
COMECAR=${COMECAR_DO_MODULO:-0}

echo "=============================================="
echo "  PIPELINE -- INICIO"
[ "$COMECAR" != "0" ] && echo "  A comecar do Modulo $COMECAR"
[ "$PARAR"   != "3" ] && echo "  A parar apos Modulo $PARAR"
echo "=============================================="
echo ""

# patches e verificacao de shapefile correm sempre (sao rapidos e necessarios)
echo ">>> PASSO 0: Aplicando patches ao HANTS..."
python3 "$WORKDIR/aplicar_patches.py"
echo ""

echo ">>> PASSO 1: Verificando CRS do shapefile..."
python3 "$WORKDIR/verificar_shp.py"
echo ""

# -----------------------------------------------------------------------------
if [ "$COMECAR" -le "0" ]; then
    echo ">>> MODULO 0: Processamento Topografico..."
    python3 "$WORKDIR/0-topografia.py"
    echo ""
else
    echo ">>> MODULO 0: [SALTADO por COMECAR_DO_MODULO=$COMECAR]"
    echo ""
fi

if [ "$PARAR" = "0" ]; then
    echo ">>> [AUDITORIA] Parando apos Modulo 0 (topografia)."
    echo "    Verifique os ficheiros em TOPOGRAFIA/ antes de continuar."
    exit 0
fi

# -----------------------------------------------------------------------------
if [ "$COMECAR" -le "1" ]; then
    echo ">>> MODULO 1: Download Sentinel-2..."
    python3 "$WORKDIR/1-download_sentinel2.py"
    echo ""
    echo ">>> AUDITORIA 1: Gerando quicklooks pos-download..."
    python3 "$WORKDIR/auditoria_modulo1.py" || echo "    [AVISO] Auditoria 1 falhou (nao critica). A continuar."
    echo ""
else
    echo ">>> MODULO 1: [SALTADO por COMECAR_DO_MODULO=$COMECAR]"
    echo ""
fi

if [ "$PARAR" = "1" ]; then
    echo ">>> [AUDITORIA] Parando apos Modulo 1 (download)."
    echo "    Verifique os quicklooks em PREVIEWS/modulo1/ antes de continuar."
    echo "    Para retomar: docker run ... -e PARAR_APOS_MODULO=3 "
    exit 0
fi

# -----------------------------------------------------------------------------
if [ "$COMECAR" -le "2" ]; then
    echo ">>> MODULO 2: HANTS -- Recorte, Suavizacao e Reprojecao..."
    python3 "$WORKDIR/2-HANTS.py"
    echo ""
    echo ">>> AUDITORIA 2: Gerando graficos de series temporais HANTS..."
    python3 "$WORKDIR/auditoria_modulo2.py" || echo "    [AVISO] Auditoria 2 falhou (nao critica). A continuar."
    echo ""
else
    echo ">>> MODULO 2: [SALTADO por COMECAR_DO_MODULO=$COMECAR]"
    echo ""
fi

if [ "$PARAR" = "2" ]; then
    echo ">>> [AUDITORIA] Parando apos Modulo 2 (HANTS)."
    echo "    Verifique as series temporais em PREVIEWS/modulo2/."
    echo "    Se necessario, ajuste hants.hiperparametros_indices em config.json"
    echo "    e relance com: docker run ... -e COMECAR_DO_MODULO=2 -e PARAR_APOS_MODULO=2 "
    exit 0
fi

# -----------------------------------------------------------------------------
echo ">>> MODULO 3: Montagem dos Datacubes..."
python3 "$WORKDIR/3-datacube.py"
echo ""

echo ">>> AUDITORIA 3: Validando datacube gerado..."
python3 "$WORKDIR/auditoria_modulo3.py" || echo "    [AVISO] Auditoria 3 falhou (nao critica)."
echo ""

echo "=============================================="
echo "  PIPELINE -- CONCLUIDO COM SUCESSO"
echo "=============================================="
