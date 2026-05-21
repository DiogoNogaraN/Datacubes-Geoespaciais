# =============================================================================
# Dockerfile -- Pipeline
# Imagem base: Python 3.11 slim (QGIS/SAGA removidos -- derivados topograficos
# calculados em Python puro com GDAL + pysheds)
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libhdf5-dev \
    libnetcdf-dev \
    gdal-bin \
    libgdal-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
# Nota: nao instalamos python3-gdal nem osgeo via pip.
# O pipeline usa rasterio (para I/O raster) e pyproj (para CRS/WKT).
# gdaldem (CLI) e usado apenas no Modulo 0 via subprocess.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# INTEGRACAO DO HANTS (GitHub: gespinoza/hants)
# =============================================================================
RUN git clone https://github.com/gespinoza/hants.git /app/hants

# Copia todos os ficheiros do projeto para o container
COPY . /app

# =============================================================================
# Volume unico -- mapear a raiz do HD para /dados dentro do container
#
#   Windows:  docker run -v "D:\SeuHD:/dados" ...
#   Linux/Mac: docker run -v /mnt/hd/SeuHD:/dados ...
#
# Estrutura esperada no HD (criada pelo script setup_cliente.bat / .sh):
#   HD/
#     clientes/
#       NOME_CLIENTE/
#         inputs/          <- colocar aqui o shapefile (.shp e ficheiros auxiliares)
#         TOPOGRAFIA/      <- gerado pelo Modulo 0
#         NDVI/, NDRE/, .. <- gerado pelo Modulo 1
#         HANTS/           <- gerado pelo Modulo 2
#         HANTS_REPROJETADO/
#         DATACUBE/        <- gerado pelo Modulo 3
#
# Variaveis de ambiente disponiveis (passar com -e no docker run):
#   CLIENTE_NOME, SHP_FILENAME, SRC_PROJETO, DATA_INICIO, DATA_FIM,
#   FREQUENCIA, MESES_SAFRA, COPERNICUS_USER, COPERNICUS_PASS,
#   PARAR_APOS_MODULO
#
# Exemplos (ajustar a letra do HD conforme necessario):
#
#   # Cafe -- mensal, ano todo, UTM 23S
#   docker run -v "D:\SeuHD:/dados" \
#     -e CLIENTE_NOME=Fazenda_Cafe \
#     -e SRC_PROJETO=EPSG:32723 \
#     -e FREQUENCIA=mensal \
#     -e COPERNICUS_USER=email@email.com \
#     -e COPERNICUS_PASS=senha \
#     
#
#   # Soja -- semanal, out-jan, UTM 22S, shapefile com nome diferente
#   docker run -v "D:\SeuHD:/dados" \
#     -e CLIENTE_NOME=Fazenda_Soja \
#     -e SHP_FILENAME=area_soja.shp \
#     -e SRC_PROJETO=EPSG:32722 \
#     -e FREQUENCIA=semanal \
#     -e MESES_SAFRA=10,11,12,1 \
#     -e COPERNICUS_USER=email@email.com \
#     -e COPERNICUS_PASS=senha \
#     
# =============================================================================

# entrypoint.sh aplica as variaveis de ambiente ao config.json antes do pipeline
ENTRYPOINT ["bash", "/app/entrypoint.sh"]
