#!/bin/bash
# ============================================================
# setup_cliente.sh --
# Cria a estrutura de pastas para um novo cliente no HD.
#
# Uso: ./setup_cliente.sh /caminho/SEU_HD NOME_CLIENTE
# Exemplo: ./setup_cliente.sh /mnt/hd/SEU_HD Fazenda_Cafe
# ============================================================

if [ -z "$2" ]; then
    echo "Uso: $0 /caminho/SEU_HD NOME_CLIENTE"
    echo "Exemplo: $0 /mnt/hd/SEU_HD Fazenda_Cafe"
    exit 1
fi

BASE="$1/clientes/$2"

echo "Criando estrutura de pastas para: $2"
echo "Base: $BASE"
echo ""

mkdir -p "$BASE/inputs"
mkdir -p "$BASE/TOPOGRAFIA"
mkdir -p "$BASE/HANTS"
mkdir -p "$BASE/HANTS_REPROJETADO"
mkdir -p "$BASE/DATACUBE"

echo "[OK] Estrutura criada com sucesso!"
echo ""
echo "Proximos passos:"
echo "  1. Copiar o shapefile da propriedade para:"
echo "     $BASE/inputs/"
echo "  2. Executar o pipeline Docker:"
echo "     docker run -v \"$1:/dados\" -e CLIENTE_NOME=$2 ... "
