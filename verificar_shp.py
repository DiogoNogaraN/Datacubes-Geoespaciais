"""
verificar_shp.py
Verifica se o shapefile da propriedade esta no CRS de referencia do projeto.
Se nao estiver (ou se nao tiver CRS definido), cria uma versao reprojetada e
actualiza caminho_shp em config.json para apontar para ela.

Executado automaticamente pelo executar_pipeline.sh antes de qualquer modulo.
"""
import os
import json
import sys
import geopandas as gpd
from pyproj import CRS

CONFIG_PATH = '/app/config.json'

try:
    with open(CONFIG_PATH) as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"[ERRO CRITICO] {CONFIG_PATH} nao encontrado.")
    sys.exit(1)

caminho_shp = config['parametros_gerais']['caminho_shp']
src_projeto  = config['parametros_gerais']['src_projeto']

print(f"[SHP] Verificando shapefile: {caminho_shp}")
print(f"[SHP] CRS de referencia do projeto: {src_projeto}")

# --- 1. Verificar existencia ---
if not os.path.exists(caminho_shp):
    print(f"[ERRO CRITICO] Shapefile nao encontrado: {caminho_shp}")
    print("               Certifique-se de que o ficheiro esta em inputs/ dentro da pasta do cliente.")
    sys.exit(1)

# --- 2. Ler shapefile ---
try:
    gdf = gpd.read_file(caminho_shp)
except Exception as e:
    print(f"[ERRO CRITICO] Falha ao ler shapefile: {e}")
    sys.exit(1)

crs_projeto = CRS.from_user_input(src_projeto)

# --- 3. Sem CRS definido: atribuir o CRS do projeto ---
if gdf.crs is None:
    print(f"[AVISO] Shapefile sem CRS definido. A assumir {src_projeto}.")
    gdf = gdf.set_crs(crs_projeto)
    gdf.to_file(caminho_shp)
    print(f"[OK] CRS {src_projeto} atribuido e guardado no shapefile original.")
    sys.exit(0)

crs_shp = CRS.from_user_input(gdf.crs)

# --- 4. CRS correcto: nada a fazer ---
if crs_shp.equals(crs_projeto):
    print(f"[OK] Shapefile ja esta em {src_projeto}. Nenhuma accao necessaria.")
    sys.exit(0)

# --- 5. CRS diferente: reprojetar e guardar copia ---
epsg_str    = src_projeto.replace(':', '_')   # EPSG:32722 -> EPSG_32722
base, ext   = os.path.splitext(caminho_shp)
caminho_utm = f"{base}_{epsg_str}{ext}"

print(f"[AVISO] CRS do shapefile ({crs_shp.to_string()}) difere do projeto ({src_projeto}).")

if not os.path.exists(caminho_utm):
    print(f"         A reprojetar para {src_projeto}...")
    try:
        gdf_utm = gdf.to_crs(crs_projeto)
        gdf_utm.to_file(caminho_utm)
        print(f"[OK] Shapefile reprojetado guardado em: {caminho_utm}")
    except Exception as e:
        print(f"[ERRO CRITICO] Falha na reprojecao do shapefile: {e}")
        sys.exit(1)
else:
    print(f"[OK] Versao reprojetada ja existe: {caminho_utm}")

# --- 6. Actualizar config.json ---
config['parametros_gerais']['caminho_shp'] = caminho_utm
try:
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"[OK] config.json actualizado: caminho_shp -> {caminho_utm}")
except Exception as e:
    print(f"[ERRO CRITICO] Falha ao actualizar config.json: {e}")
    sys.exit(1)
