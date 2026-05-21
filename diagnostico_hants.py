"""
diagnostico_hants.py
Diagnostico detalhado do pipeline HANTS para identificar onde os dados se perdem.

Execucao dentro do container:
  docker run --rm -v "D:\\SEU_HD:/dados" \
    -e CLIENTE_NOME=Nome_Cliente -e SHP_FILENAME=fazenda.shp \
    -e SRC_PROJETO=EPSG:32722 \
    -e COPERNICUS_USER=... -e COPERNICUS_PASS=... \
    --entrypoint python3 SEU_HD /app/diagnostico_hants.py
"""
import os, sys, json, glob
import numpy as np
import rasterio
import geopandas as gpd

SEP = "=" * 60

# --- Config ---
try:
    with open('/app/config.json') as f:
        config = json.load(f)
except:
    print("ERRO: /app/config.json nao encontrado.")
    sys.exit(1)

pasta_cliente  = config['cliente']['pasta_destino']
src_destino    = config['parametros_gerais']['src_projeto']
caminho_shp    = config['parametros_gerais']['caminho_shp']
primeiro_indice = config['download']['indices'][0]   # NDVI

print(SEP)
print("  DIAGNOSTICO HANTS ")
print(SEP)

# =====================================================================
# 1. SHAPEFILE
# =====================================================================
print("\n[1] SHAPEFILE")
try:
    gdf = gpd.read_file(caminho_shp)
    aoi_utm = gdf.to_crs(src_destino)
    bounds  = aoi_utm.total_bounds
    print(f"    Ficheiro  : {caminho_shp}")
    print(f"    CRS orig  : {gdf.crs}")
    print(f"    CRS UTM   : {aoi_utm.crs}")
    print(f"    Bounds UTM: xmin={bounds[0]:.1f}  ymin={bounds[1]:.1f}  xmax={bounds[2]:.1f}  ymax={bounds[3]:.1f}")
    print(f"    Largura   : {bounds[2]-bounds[0]:.1f} m    Altura: {bounds[3]-bounds[1]:.1f} m")
except Exception as e:
    print(f"    ERRO: {e}")

# =====================================================================
# 2. IMAGENS ORIGINAIS (pasta NDVI/)
# =====================================================================
print(f"\n[2] IMAGENS ORIGINAIS ({primeiro_indice}/)")
pasta_orig = os.path.join(pasta_cliente, primeiro_indice)
imgs_orig  = sorted(glob.glob(os.path.join(pasta_orig, "*.tif")))
print(f"    Total de ficheiros: {len(imgs_orig)}")
if imgs_orig:
    with rasterio.open(imgs_orig[0]) as src:
        dados = src.read(1).astype(np.float32)
        nd    = src.nodata
        if nd is not None:
            dados[dados == nd] = np.nan
        else:
            dados[~np.isfinite(dados)] = np.nan
        print(f"    Exemplo   : {os.path.basename(imgs_orig[0])}")
        print(f"    CRS       : {src.crs}")
        print(f"    Resolucao : {src.transform.a:.6f} x {abs(src.transform.e):.6f}")
        print(f"    Dimensao  : {src.width} x {src.height} pixels")
        print(f"    Bounds    : {src.bounds}")
        validos = dados[np.isfinite(dados)]
        print(f"    Pixeis validos: {len(validos)} / {dados.size}  ({100*len(validos)/dados.size:.1f}%)")
        if len(validos):
            print(f"    Min={validos.min():.4f}  Max={validos.max():.4f}  Media={validos.mean():.4f}")
        else:
            print("    *** TODOS OS PIXELS SAO NaN/NoData! ***")

# =====================================================================
# 3. IMAGENS TEMP_UTM (apos reprojecao + recorte)
# =====================================================================
print(f"\n[3] IMAGENS TEMP_UTM ({primeiro_indice}/)")
pasta_utm = os.path.join(pasta_cliente, "TEMP_UTM", primeiro_indice)
imgs_utm  = sorted(glob.glob(os.path.join(pasta_utm, "*.tif")))
print(f"    Total de ficheiros: {len(imgs_utm)}")
if imgs_utm:
    with rasterio.open(imgs_utm[0]) as src:
        dados = src.read(1).astype(np.float32)
        nd    = src.nodata
        if nd is not None:
            dados[np.isclose(dados, nd)] = np.nan
        else:
            dados[~np.isfinite(dados)] = np.nan
        t = src.transform
        print(f"    Exemplo   : {os.path.basename(imgs_utm[0])}")
        print(f"    CRS       : {src.crs}")
        print(f"    Resolucao : {t.a:.4f} x {abs(t.e):.4f} m")
        print(f"    Dimensao  : {src.width} x {src.height} pixels")
        print(f"    Transform : c(xmin)={t.c:.2f}  f(ymax)={t.f:.2f}")
        print(f"    Bounds    : {src.bounds}")
        validos = dados[np.isfinite(dados)]
        print(f"    Pixeis validos: {len(validos)} / {dados.size}  ({100*len(validos)/dados.size:.1f}%)")
        if len(validos):
            print(f"    Min={validos.min():.4f}  Max={validos.max():.4f}  Media={validos.mean():.4f}")
        else:
            print("    *** TODOS OS PIXELS SAO NaN/NoData! ***")

# =====================================================================
# 4. GRADE HANTS (como seria calculada no 2-HANTS.py)
# =====================================================================
print(f"\n[4] GRADE HANTS")
if imgs_utm:
    with rasterio.open(imgs_utm[0]) as src:
        raster_bounds = src.bounds
        pixel_size    = abs(src.transform.a)

    latlim = [float(bounds[1]), float(bounds[3])]
    lonlim = [float(bounds[0]), float(bounds[2])]
    cs = 10.0

    lat_coords = np.arange(latlim[0] + cs/2, latlim[1], cs)
    lon_coords = np.arange(lonlim[0] + cs/2, lonlim[1], cs)
    lat_n, lon_n = len(lat_coords), len(lon_coords)

    print(f"    latlim (Y): [{latlim[0]:.2f}, {latlim[1]:.2f}]  -> {lat_n} celulas")
    print(f"    lonlim (X): [{lonlim[0]:.2f}, {lonlim[1]:.2f}]  -> {lon_n} celulas")
    print(f"    cellsize  : {cs} m")
    print(f"    Grade total: {lon_n} x {lat_n} pixels")

    # Simular Raster_to_Array
    print(f"\n[5] SIMULACAO Raster_to_Array")
    with rasterio.open(imgs_utm[0]) as src:
        t = src.transform
        top_left_x = t.c
        cellsize_x = t.a
        top_left_y = t.f
        cellsize_y = t.e   # negativo
        ras_w      = src.width
        ras_h      = src.height

    xmin_arr = lonlim[0]
    ymin_arr = latlim[0]

    x_off = int(round((xmin_arr - top_left_x) / cellsize_x))
    y_off = int(round((top_left_y - (ymin_arr + lat_n * abs(cellsize_y))) / abs(cellsize_y)))

    src_x = max(0, x_off)
    src_y = max(0, y_off)
    dst_x = max(0, -x_off)
    dst_y = max(0, -y_off)

    win_w = min(lon_n - dst_x, ras_w - src_x)
    win_h = min(lat_n - dst_y, ras_h - src_y)

    print(f"    Raster top-left : X={top_left_x:.2f}  Y={top_left_y:.2f}")
    print(f"    Raster pixelsize: {cellsize_x:.4f} x {cellsize_y:.4f}")
    print(f"    Raster dimensao : {ras_w} x {ras_h}")
    print(f"    HANTS ll_corner : X={xmin_arr:.2f}  Y={ymin_arr:.2f}")
    print(f"    x_offset        : {x_off}  (src_x={src_x}, dst_x={dst_x})")
    print(f"    y_offset        : {y_off}  (src_y={src_y}, dst_y={dst_y})")
    print(f"    Janela leitura  : {win_w} x {win_h} pixels")
    if win_w <= 0 or win_h <= 0:
        print("    *** JANELA ZERO OU NEGATIVA -> DADOS NAO SAO LIDOS! ***")
        print("    *** CAUSA PROVAVEL: BOUNDS DO SHAPEFILE NAO COINCIDEM COM A GRELHA DO RASTER ***")
    else:
        print(f"    Cobertura       : {100*win_w/lon_n:.1f}% largura  {100*win_h/lat_n:.1f}% altura")

# =====================================================================
# 5. IMAGENS HANTS OUTPUT
# =====================================================================
print(f"\n[6] IMAGENS HANTS OUTPUT ({primeiro_indice}/)")
pasta_hants = os.path.join(pasta_cliente, "HANTS", primeiro_indice)
imgs_hants  = sorted(glob.glob(os.path.join(pasta_hants, "*.tif")))
print(f"    Total de ficheiros: {len(imgs_hants)}")
if imgs_hants:
    with rasterio.open(imgs_hants[0]) as src:
        dados = src.read(1).astype(np.float32)
        nd    = src.nodata
        print(f"    Exemplo  : {os.path.basename(imgs_hants[0])}")
        print(f"    CRS      : {src.crs}")
        print(f"    Dimensao : {src.width} x {src.height}")
        print(f"    Bounds   : {src.bounds}")
        print(f"    nodata   : {nd}")
        if nd is not None:
            dados[np.isclose(dados, nd)] = np.nan
        else:
            dados[~np.isfinite(dados)] = np.nan
        validos = dados[np.isfinite(dados)]
        print(f"    Pixeis validos: {len(validos)} / {dados.size}  ({100*len(validos)/dados.size:.1f}%)")
        if len(validos):
            print(f"    Min={validos.min():.4f}  Max={validos.max():.4f}  Media={validos.mean():.4f}")
        else:
            print("    *** TODOS OS PIXELS SAO fill_value (-9999)! ***")
            print("    *** O HANTS nao recebeu dados validos. ***")

print(f"\n{SEP}")
print("  FIM DO DIAGNOSTICO")
print(SEP)
