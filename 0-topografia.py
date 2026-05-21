import os
import json
import math
import subprocess
import shutil
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject

print("--- Iniciando Modulo 0: Processamento Topografico ---")

# =====================================================================
# ETAPA 1: LER CONFIGURACOES
# =====================================================================
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print("ERRO CRITICO: Ficheiro config.json nao encontrado.")
    exit(1)

caminho_shp         = config['parametros_gerais']['caminho_shp']
src_projeto         = config['parametros_gerais']['src_projeto']
caminho_modelo_qgis = config['topografia']['caminho_modelo_qgis']
pasta_topo          = config['topografia']['pasta_inputs_qgis']
buffer_graus        = config['topografia'].get('buffer_download_dem_graus', 0.1)

os.makedirs(pasta_topo, exist_ok=True)

# Ficheiros intermediarios e finais
caminho_dem_merged   = os.path.join(pasta_topo, "dem_tiles_merged_30m.tif")
caminho_dem_10m_full = os.path.join(pasta_topo, "dem_upsampled_10m_full.tif")
caminho_dem_10m_utm  = os.path.join(pasta_topo, "dem_upsampled_10m_utm.tif")
caminho_dem_10m_clip = os.path.join(pasta_topo, "dem_10m_recortado.tif")

# =====================================================================
# ETAPA 2: LER SHAPEFILE E CALCULAR BBOX COM BUFFER
# =====================================================================
print("\n-> 1. Lendo shapefile e calculando area de download...")
try:
    aoi_gdf  = gpd.read_file(caminho_shp)
    aoi_4326 = aoi_gdf.to_crs(epsg=4326)
    bounds   = aoi_4326.total_bounds   # [minx, miny, maxx, maxy]
    lon_min  = bounds[0] - buffer_graus
    lat_min  = bounds[1] - buffer_graus
    lon_max  = bounds[2] + buffer_graus
    lat_max  = bounds[3] + buffer_graus
    print(f"  [OK] BBox com buffer {buffer_graus} grau(s): lon=[{lon_min:.4f}, {lon_max:.4f}], lat=[{lat_min:.4f}, {lat_max:.4f}]")
except Exception as e:
    print(f"  [ERRO] Falha ao ler shapefile: {e}")
    exit(1)

# =====================================================================
# ETAPA 3: DOWNLOAD DOS TILES COPERNICUS DEM GLO-30 (AWS S3 / COG)
# =====================================================================
def nome_tile_copernicus(lat_tile, lon_tile):
    """Gera o nome do tile Copernicus DEM GLO-30 a partir do canto SW (inteiros)."""
    ns = "N" if lat_tile >= 0 else "S"
    ew = "E" if lon_tile >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat_tile):02d}_00_{ew}{abs(lon_tile):03d}_00_DEM"

def url_tile_copernicus(nome):
    return f"https://copernicus-dem-30m.s3.amazonaws.com/{nome}/{nome}.tif"

def identificar_tiles(lon_min, lat_min, lon_max, lat_max):
    """Lista os tiles 1x1 grau que cobrem completamente a bounding box."""
    tiles = []
    for lat in range(math.floor(lat_min), math.floor(lat_max) + 1):
        for lon in range(math.floor(lon_min), math.floor(lon_max) + 1):
            nome = nome_tile_copernicus(lat, lon)
            tiles.append((nome, url_tile_copernicus(nome)))
    return tiles

if not os.path.exists(caminho_dem_merged):
    print("\n-> 2. Descarregando tiles do Copernicus DEM GLO-30 via AWS S3 (COG/vsicurl)...")
    tiles = identificar_tiles(lon_min, lat_min, lon_max, lat_max)
    print(f"  Tiles identificados: {len(tiles)}")

    datasets_abertos = []
    try:
        for nome, url in tiles:
            vsicurl_path = f"/vsicurl/{url}"
            print(f"  Abrindo tile: {nome} ...")
            try:
                ds = rasterio.open(vsicurl_path)
                datasets_abertos.append(ds)
                print(f"    [OK]")
            except Exception as e:
                print(f"    [AVISO] Tile indisponivel (oceano ou fora do catalogo): {e}")

        if not datasets_abertos:
            print("  [ERRO] Nenhum tile DEM encontrado para a area definida.")
            exit(1)

        print(f"  Mesclando {len(datasets_abertos)} tile(s) em mosaico unico...")
        mosaic, out_transform = merge(datasets_abertos)

        out_meta = datasets_abertos[0].meta.copy()
        out_meta.update({
            "driver":    "GTiff",
            "height":    mosaic.shape[1],
            "width":     mosaic.shape[2],
            "transform": out_transform,
            "crs":       datasets_abertos[0].crs,
            "compress":  "lzw"
        })
        with rasterio.open(caminho_dem_merged, "w", **out_meta) as dest:
            dest.write(mosaic)

        print(f"  [OK] Mosaico DEM 30m salvo: {mosaic.shape[2]}x{mosaic.shape[1]} pixels")

    finally:
        for ds in datasets_abertos:
            ds.close()
else:
    print("\n-> 2. Mosaico DEM 30m ja existe. Pulando download.")

# =====================================================================
# ETAPA 4: REAMOSTRAGEM 30m -> 10m (AREA COMPLETA, SEM RECORTE, EM 4326)
# Feita antes da reprojecao para evitar artefactos nas bordas: a grade de
# 30m seria reamostrada de forma inconsistente se ja estivesse em UTM.
# =====================================================================
if not os.path.exists(caminho_dem_10m_full):
    print("\n-> 3. Reamostrando DEM para 10m em EPSG:4326 (area completa)...")
    try:
        fator = 3  # 30m / 3 = 10m
        with rasterio.open(caminho_dem_merged) as src:
            novo_width  = src.width  * fator
            novo_height = src.height * fator
            novo_transform = src.transform * src.transform.scale(
                src.width  / novo_width,
                src.height / novo_height
            )
            dados = src.read(
                out_shape=(src.count, novo_height, novo_width),
                resampling=Resampling.cubic
            )
            perfil = src.profile.copy()
            perfil.update({
                "width":     novo_width,
                "height":    novo_height,
                "transform": novo_transform,
                "compress":  "lzw"
            })
            with rasterio.open(caminho_dem_10m_full, "w", **perfil) as dst:
                dst.write(dados)
        print(f"  [OK] DEM reamostrado: {novo_width}x{novo_height} pixels (~10m/pixel, EPSG:4326)")
    except Exception as e:
        print(f"  [ERRO] Falha na reamostragem: {e}")
        exit(1)
else:
    print("\n-> 3. Reamostragem ja realizada anteriormente. Pulando etapa.")

# =====================================================================
# ETAPA 5: REPROJECAO PARA CRS PLANO (src_projeto)
# Necessario antes do QGIS: calculos de declive, aspecto e SWI requerem
# pixels em metros (CRS plano) para producir resultados correctos.
# Reprojecao e feita sobre a area completa (ainda sem recorte).
# =====================================================================
if not os.path.exists(caminho_dem_10m_utm):
    print(f"\n-> 4. Reprojetando DEM para {src_projeto} (area completa, antes do recorte)...")
    try:
        with rasterio.open(caminho_dem_10m_full) as src:
            transform_dst, width_dst, height_dst = calculate_default_transform(
                src.crs, src_projeto, src.width, src.height, *src.bounds
            )
            perfil = src.profile.copy()
            perfil.update({
                "crs":       src_projeto,
                "transform": transform_dst,
                "width":     width_dst,
                "height":    height_dst,
                "compress":  "lzw"
            })
            with rasterio.open(caminho_dem_10m_utm, "w", **perfil) as dst:
                for i in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform_dst,
                        dst_crs=src_projeto,
                        resampling=Resampling.cubic
                    )
        print(f"  [OK] DEM reprojetado: {width_dst}x{height_dst} pixels em {src_projeto}")
    except Exception as e:
        print(f"  [ERRO] Falha na reprojecao: {e}")
        exit(1)
else:
    print(f"\n-> 4. Reprojecao para {src_projeto} ja realizada. Pulando etapa.")

# =====================================================================
# ETAPA 6: RECORTE DO DEM 10m COM BASE NO SHAPEFILE (em CRS plano)
# =====================================================================
if not os.path.exists(caminho_dem_10m_clip):
    print("\n-> 5. Recortando DEM 10m com o shapefile da propriedade...")
    try:
        with rasterio.open(caminho_dem_10m_utm) as src:
            aoi_reprojected = aoi_gdf.to_crs(src.crs)
            geometrias_clip = [geom for geom in aoi_reprojected.geometry]

            out_image, out_transform = mask(src, geometrias_clip, crop=True, nodata=np.nan)

            perfil = src.profile.copy()
            perfil.update({
                "height":    out_image.shape[1],
                "width":     out_image.shape[2],
                "transform": out_transform,
                "nodata":    np.nan,
                "compress":  "lzw"
            })
            with rasterio.open(caminho_dem_10m_clip, "w", **perfil) as dst:
                dst.write(out_image)

        print(f"  [OK] DEM recortado: {out_image.shape[2]}x{out_image.shape[1]} pixels em {src_projeto}")
    except Exception as e:
        print(f"  [ERRO] Falha no recorte: {e}")
        exit(1)
else:
    print("\n-> 5. Recorte ja realizado anteriormente. Pulando etapa.")

# =====================================================================
# ETAPA 7: DERIVADOS TOPOGRAFICOS EM PYTHON PURO
# Calculados com GDAL (declive/aspecto) + pysheds (TWI/SWI).
# Nao requer QGIS nem SAGA — totalmente portavel em Docker.
# =====================================================================
out_swi         = os.path.join(pasta_topo, "SWI.tif")
out_declividade = os.path.join(pasta_topo, "declividade.tif")
out_altitude    = os.path.join(pasta_topo, "altitude.tif")
out_nortecidade = os.path.join(pasta_topo, "nortecidade.tif")
out_lestecidade = os.path.join(pasta_topo, "lestecidade.tif")
out_aspecto     = os.path.join(pasta_topo, "aspecto.tif")

topo_ja_calculado = all(
    os.path.exists(p) for p in [out_swi, out_declividade, out_nortecidade, out_lestecidade, out_aspecto]
)

if not topo_ja_calculado:
    print("\n-> 6. Calculando derivados topograficos em Python (GDAL + pysheds)...")

    # -- 6.1 Declive (graus) via gdaldem -----------------------------------
    try:
        ret = subprocess.run(
            ["gdaldem", "slope", caminho_dem_10m_clip, out_declividade, "-s", "1", "-co", "COMPRESS=LZW"],
            check=True, capture_output=True, text=True
        )
        print("  [OK] Declive calculado (gdaldem slope)")
    except subprocess.CalledProcessError as e:
        print(f"  [ERRO] gdaldem slope: {e.stderr}"); exit(1)

    # -- 6.2 Aspecto (graus) via gdaldem -----------------------------------
    try:
        ret = subprocess.run(
            ["gdaldem", "aspect", caminho_dem_10m_clip, out_aspecto, "-zero_for_flat", "-co", "COMPRESS=LZW"],
            check=True, capture_output=True, text=True
        )
        print("  [OK] Aspecto calculado (gdaldem aspect)")
    except subprocess.CalledProcessError as e:
        print(f"  [ERRO] gdaldem aspect: {e.stderr}"); exit(1)

    # -- 6.3 Nortecidade e Lestecidade a partir do aspecto -----------------
    try:
        with rasterio.open(out_aspecto) as src_asp:
            asp_deg  = src_asp.read(1).astype(np.float32)
            nodata_a = src_asp.nodata
            perfil_asp = src_asp.profile.copy()

        mascara_valida = (asp_deg != nodata_a) if nodata_a is not None else np.isfinite(asp_deg)
        asp_rad = np.where(mascara_valida, np.deg2rad(asp_deg), np.nan)

        norte = np.cos(asp_rad).astype(np.float32)
        leste = np.sin(asp_rad).astype(np.float32)

        perfil_asp.update({"dtype": "float32", "nodata": np.nan})
        with rasterio.open(out_nortecidade, "w", **perfil_asp) as dst:
            dst.write(norte, 1)
        with rasterio.open(out_lestecidade, "w", **perfil_asp) as dst:
            dst.write(leste, 1)
        print("  [OK] Nortecidade e Lestecidade calculadas")
    except Exception as e:
        print(f"  [ERRO] Nortecidade/Lestecidade: {e}"); exit(1)

    # -- 6.4 TWI/SWI via pysheds com D-infinity (Topographic Wetness Index) --
    # D-infinity (Tarboton 1997): distribui fluxo por ate 2 celulas vizinhas
    # proporcionalmente ao angulo — precisao proxima ao MFD do SAGA, sem dependencia
    # de QGIS/SAGA no container.
    try:
        from pysheds.grid import Grid

        grid   = Grid.from_raster(caminho_dem_10m_clip)
        dem_ps = grid.read_raster(caminho_dem_10m_clip)

        # Pre-processar DEM: preencher pits, depressoes e aplainar
        pit_filled = grid.fill_pits(dem_ps)
        flooded    = grid.fill_depressions(pit_filled)
        inflated   = grid.resolve_flats(flooded)

        # Direcao e acumulacao de fluxo com D-infinity
        fdir = grid.flowdir(inflated, routing="dinf")
        acc  = grid.accumulation(fdir, routing="dinf")

        # Ler declive e obter tamanho do pixel
        with rasterio.open(out_declividade) as src_slope:
            slope_deg  = src_slope.read(1).astype(np.float32)
            nodata_s   = src_slope.nodata
            perfil_twi = src_slope.profile.copy()
            pixel_size = abs(src_slope.transform.a)   # metros

        mascara_s = (slope_deg != nodata_s) if nodata_s is not None else np.isfinite(slope_deg)

        # Evitar tan(0): clip minimo de 0.1 grau (relevo muito plano)
        slope_rad = np.where(mascara_s, np.deg2rad(np.clip(slope_deg, 0.1, 89.9)), 0.1)

        # TWI = ln( area_contribuinte / tan(declive) )
        # area_contribuinte = (acc + 1) * pixel_area  (+1 para incluir a propria celula)
        acc_arr = np.array(acc).astype(np.float32)
        twi     = np.log(np.maximum((acc_arr + 1) * (pixel_size ** 2) / np.tan(slope_rad), 1e-6))
        twi     = twi.astype(np.float32)
        twi[~mascara_s] = np.nan

        perfil_twi.update({"dtype": "float32", "nodata": np.nan, "compress": "lzw"})
        with rasterio.open(out_swi, "w", **perfil_twi) as dst:
            dst.write(twi, 1)
        print(f"  [OK] SWI/TWI calculado (pysheds D-inf) — min={float(np.nanmin(twi)):.2f}, max={float(np.nanmax(twi)):.2f}")

    except Exception as e:
        print(f"  [ERRO] SWI/TWI (pysheds): {e}"); exit(1)

    # -- 6.5 Altitude = copia do DEM recortado (padroniza nomes para Modulo 3)
    shutil.copy(caminho_dem_10m_clip, out_altitude)
    print("  [OK] Altitude copiada do DEM recortado")

else:
    print("\n-> 6. Mapas topograficos ja existem. Pulando calculo.")

print("\n--- Modulo 0 (Topografia) Concluido e Pronto para o Datacube! ---")
