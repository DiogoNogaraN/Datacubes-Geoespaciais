#!/bin/bash
# ============================================================
# processar_areas.sh 
# Processa multiplas areas de um mesmo cliente em sequencia.
# Le as configuracoes de areas_lote.json.
#
# Uso: ./processar_areas.sh [areas_lote.json] [/caminho/SEU_HD]
# Padrao: areas_lote.json no diretorio atual, /mnt/hd/SEU_HD
# ============================================================
set -e

LOTE_FILE="${1:-areas_lote.json}"
HD_PATH="${2:-/mnt/hd/SEU_HD}"

if [ ! -f "$LOTE_FILE" ]; then
    echo "ERRO: Ficheiro $LOTE_FILE nao encontrado."
    exit 1
fi

# Extrair campos do cliente
eval $(python3 -c "
import json, sys
d = json.load(open('$LOTE_FILE'))
c = d['cliente']
for k, v in c.items():
    print(f\"{k.upper()}='{v}'\")
")

echo "============================================================"
echo " Processamento em Lote"
echo " Cliente : $NOME"
echo " HD      : $HD_PATH"
echo " Periodo : $DATA_INICIO a $DATA_FIM"
echo "============================================================"
echo

LOG_BASE="$HD_PATH/clientes/$NOME/logs_pipeline"
mkdir -p "$LOG_BASE"

# Iterar sobre cada area
python3 -c "
import json
d = json.load(open('$LOTE_FILE'))
for a in d['areas']:
    print(a['nome'] + '|' + a.get('shp_filename','contorno_fazenda.shp') + '|' + a.get('parar_apos',''))
" | while IFS='|' read -r AREA SHP PARAR; do

    echo "----------------------------------------------------------"
    echo " Iniciando area: $AREA"
    echo "----------------------------------------------------------"

    LOG_FILE="$LOG_BASE/${AREA}.log"
    PARAR_OPT=""
    [ -n "$PARAR" ] && PARAR_OPT="-e PARAR_APOS_MODULO=$PARAR"

    docker run --rm \
      -v "$HD_PATH:/dados" \
      -e CLIENTE_NOME="$NOME" \
      -e NOME_AREA="$AREA" \
      -e SHP_FILENAME="$SHP" \
      -e SRC_PROJETO="$SRC_PROJETO" \
      -e FREQUENCIA="$FREQUENCIA" \
      -e MESES_SAFRA="$MESES_SAFRA" \
      -e DATA_INICIO="$DATA_INICIO" \
      -e DATA_FIM="$DATA_FIM" \
      -e COPERNICUS_USER="$COPERNICUS_USER" \
      -e COPERNICUS_PASS="$COPERNICUS_PASS" \
      $PARAR_OPT \
      2>&1 | tee "$LOG_FILE"

    if [ $? -ne 0 ]; then
        echo "[ERRO] Area $AREA falhou. Ver log em $LOG_FILE"
    else
        echo "[OK] Area $AREA concluida."
    fi
    echo
done

echo "============================================================"
echo " Lote concluido. Logs em: $LOG_BASE/"
echo "============================================================"
