#!/bin/bash
# =============================================================================
# entrypoint.sh — Docker Entrypoint
#
# Ponto de entrada do container. Executa SEMPRE antes do pipeline:
#   1. Aplica variáveis de ambiente ao config.json
#   2. Arranca o pipeline completo (executar_pipeline.sh)
#
# Para personalizar uma execução, passa as variáveis com -e no docker run.
# Ver configurar_ambiente.py para a lista completa de variáveis suportadas.
# =============================================================================

set -e

echo "=============================================="
echo "  Inicializando Container"
echo "=============================================="
echo ""

# Aplica variáveis de ambiente ao config.json (se definidas)
python3 /app/configurar_ambiente.py

# Arranca o pipeline
exec bash /app/executar_pipeline.sh
