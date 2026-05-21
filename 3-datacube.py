"""
3-datacube.py -- AgroSirius  Modulo 3

Monta dois datacubes NumPy a partir dos outputs do Modulo 2:

  IV_{nome}_norm01.npy
      Shape: (T, H, W, F)
        T = numero de periodos temporais (ex: 52 meses)
        H = altura em pixeis
        W = largura em pixeis
        F = numero de indices de vegetacao (ex: 9)

      Organizacao: dc_iv[t] contem TODOS os F indices para o periodo t,
      sempre na mesma ordem definida em config['download']['indices'].
      dc_iv[t, :, :, 0] = NDVI do periodo t
      dc_iv[t, :, :, 1] = NDRE do periodo t
      ...
      dc_iv[t, :, :, F-1] = ultimo indice do periodo t

      Normalizacao: Min-Max por imagem [0.0, 1.0].
      Cada fatia (t, f) e normalizada pelo seu proprio minimo e maximo
      espacial, preservando a variabilidade relativa dentro de cada periodo
      e tornando os valores comparaveis entre indices de escalas diferentes.
      Pixeis sem dados (nodata / fora da fazenda) = NaN.

  Estatico_{nome}_norm01.npy
      Shape: (V, H, W)
        V = numero de variaveis topograficas (ex: 5)

      Normalizacao: Min-Max por variavel [0.0, 1.0].

Todos os mapas partilham exactamente o mesmo grid espacial
(mesmo CRS, transform, resolucao e dimensoes). Qualquer raster
com grid ligeiramente diferente e reprojetado em memoria para
o grid de referencia antes de ser inserido no datacube.
"""

import os
import json
import glob
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.mask import mask as rio_mask
from rasterio.transform import Affine
import geopandas as gpd

print("--- Iniciando Modulo 3: Montagem dos Datacubes ---")

# =====================================================================
# 1. CONFIGURACAO
# =====================================================================
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print("ERRO CRITICO: config.json nao encontrado.")
    exit(1)

pasta_cliente       = config['cliente']['pasta_destino']
nome_cliente        = config['cliente']['nome']
caminho_shp         = config['parametros_gerais']['caminho_shp']
indices_processados = config['download']['indices']   # ordem canonica dos indices
variaveis_topo      = config['topografia']['variaveis']
pasta_topo_inputs   = config['topografia']['pasta_inputs_qgis']

pasta_saida_dc = config['cliente'].get(
    'pasta_saida_datacube',
    os.path.join(pasta_cliente, "DATACUBE")
)
os.makedirs(pasta_saida_dc, exist_ok=True)

# =====================================================================
# 2. GRID DE REFERENCIA (primeira imagem HANTS disponivel)
# =====================================================================
caminho_molde = None
for idx_ref in indices_processados:
    pasta_ref  = os.path.join(pasta_cliente, "HANTS_REPROJETADO", idx_ref)
    candidatos = sorted(glob.glob(os.path.join(pasta_ref, "*.tif")))
    if candidatos:
        caminho_molde = candidatos[0]
        break

if caminho_molde is None:
    print("ERRO CRITICO: Nenhuma imagem HANTS encontrada.")
    exit(1)

with rasterio.open(caminho_molde) as src:
    perfil_ref   = src.profile.copy()
    transform_ref = src.transform
    crs_ref      = src.crs
    h_ref        = src.height
    w_ref        = src.width
    nd_ref       = float(src.nodata) if src.nodata is not None else -9999.0

perfil_ref.update(dtype='float32', count=1, nodata=nd_ref)

print(f"[OK] Grid de referencia: {w_ref}x{h_ref} px | CRS={crs_ref} | res={transform_ref.a:.4f} m")

# Geometria da fazenda reprojetada para o CRS do grid
aoi_gdf         = gpd.read_file(caminho_shp).to_crs(crs_ref)
geometrias_clip = list(aoi_gdf.geometry)

# =====================================================================
# 3. FUNCAO AUXILIAR: ler raster e alinhar ao grid de referencia
# =====================================================================
def ler_e_alinhar(caminho_tif):
    """
    Le um raster e reprojeta para o grid de referencia se necessario.
    Devolve (array float32 HxW, nodata_valor).
    Pixeis nodata sao preservados como nodata_valor.
    """
    with rasterio.open(caminho_tif) as src:
        ja_alinhado = (
            src.crs      == crs_ref       and
            src.height   == h_ref         and
            src.width    == w_ref         and
            abs(src.transform.a - transform_ref.a) < 1e-6 and
            abs(src.transform.e - transform_ref.e) < 1e-6 and
            abs(src.transform.c - transform_ref.c) < 1e-2 and
            abs(src.transform.f - transform_ref.f) < 1e-2
        )
        nodata_src = float(src.nodata) if src.nodata is not None else nd_ref

        if ja_alinhado:
            arr = src.read(1).astype(np.float32)
        else:
            arr = np.full((h_ref, w_ref), nodata_src, dtype=np.float32)
            reproject(
                source      = rasterio.band(src, 1),
                destination = arr,
                src_transform = src.transform,
                src_crs       = src.crs,
                dst_transform = transform_ref,
                dst_crs       = crs_ref,
                dst_nodata    = nodata_src,
                resampling    = Resampling.bilinear
            )

    return arr, nodata_src

# =====================================================================
# 4. DATACUBE TOPOGRAFICO: (V, H, W)  normalizado [0,1]
# =====================================================================
print("\n-> Processando variaveis topograficas...")
mapas_topo          = []
nomes_features_topo = []

for var in variaveis_topo:
    fp = os.path.join(pasta_topo_inputs, f"{var}.tif")
    if not os.path.exists(fp):
        print(f"  [AVISO] {var}.tif nao encontrado.")
        continue
    try:
        nd_topo = -9999.0

        with rasterio.open(fp) as src:
            nd_topo = float(src.nodata) if src.nodata is not None else -9999.0

            if src.crs == crs_ref:
                # CRS ja correcto — ler directamente
                arr_crs       = src.read(1).astype(np.float32)
                tf_crs        = src.transform
                w_crs, h_crs  = src.width, src.height
            else:
                # Passo 1: reprojetar para o CRS de referência mantendo a
                # resolucao nativa e os limites geograficos corretos.
                # Usando calculate_default_transform para garantir que os
                # bounds do raster fonte ficam totalmente representados no
                # raster destino (evita perda de dados em conversoes entre
                # zonas UTM adjacentes como 32722 <-> 32723).
                tf_crs, w_crs, h_crs = calculate_default_transform(
                    src.crs, crs_ref, src.width, src.height, *src.bounds
                )
                arr_crs = np.full((h_crs, w_crs), nd_topo, dtype=np.float32)
                reproject(
                    source        = rasterio.band(src, 1),
                    destination   = arr_crs,
                    src_transform = src.transform,
                    src_crs       = src.crs,
                    dst_transform = tf_crs,
                    dst_crs       = crs_ref,
                    dst_nodata    = nd_topo,
                    resampling    = Resampling.bilinear
                )

        # Passo 2: resamplar do CRS correcto para o grid exacto de referência
        # (mesma resolucao e extensao exata dos rasters HANTS)
        arr_final = np.full((h_ref, w_ref), nd_topo, dtype=np.float32)
        perfil_interim = {
            'driver': 'GTiff', 'dtype': 'float32', 'count': 1,
            'crs': crs_ref, 'transform': tf_crs,
            'width': w_crs, 'height': h_crs, 'nodata': nd_topo
        }
        with rasterio.io.MemoryFile() as mem_i:
            with mem_i.open(**perfil_interim) as ds_i:
                ds_i.write(arr_crs, 1)
                reproject(
                    source        = rasterio.band(ds_i, 1),
                    destination   = arr_final,
                    src_transform = tf_crs,
                    src_crs       = crs_ref,
                    dst_transform = transform_ref,
                    dst_crs       = crs_ref,
                    dst_nodata    = nd_topo,
                    resampling    = Resampling.bilinear
                )

        # Passo 3: recortar pelo shapefile da fazenda
        perfil_mask = perfil_ref.copy()
        perfil_mask.update(dtype='float32', count=1, nodata=nd_topo)
        with rasterio.io.MemoryFile() as mem_m:
            with mem_m.open(**perfil_mask) as ds_m:
                ds_m.write(arr_final, 1)
                out, _ = rio_mask(ds_m, geometrias_clip, crop=False,
                                  filled=True, nodata=np.nan)
        arr_clip = out[0]

        # Substituir nodata residual por NaN
        arr_clip[arr_clip == nd_topo] = np.nan

        v_min = float(np.nanmin(arr_clip))
        v_max = float(np.nanmax(arr_clip))
        if v_max - v_min > 1e-9:
            arr_norm = (arr_clip - v_min) / (v_max - v_min)
        else:
            arr_norm = np.full_like(arr_clip, 0.5)
        arr_norm[np.isnan(arr_clip)] = np.nan

        mapas_topo.append(arr_norm)
        nomes_features_topo.append(var)
        print(f"  [OK] {var:15s}  range={v_min:.2f} -> {v_max:.2f}")
    except Exception as e:
        print(f"  [ERRO] {var}: {e}")

if mapas_topo:
    dc_static    = np.stack(mapas_topo, axis=0)   # (V, H, W)
    path_topo    = os.path.join(pasta_saida_dc, f"Estatico_{nome_cliente}_norm01.npy")
    np.save(path_topo, dc_static)
    with open(path_topo.replace('.npy', '_feature_names.txt'), 'w') as f:
        f.write('\n'.join(nomes_features_topo))
    print(f"[OK] Datacube topografico: shape={dc_static.shape}  -> {path_topo}")
else:
    print("[AVISO] Nenhuma variavel topografica processada.")

# =====================================================================
# 5. DESCOBRIR DATAS (uniao de todos os indices)
# =====================================================================
print("\n-> Descobrindo datas disponíveis...")
datas_set = set()
for idx in indices_processados:
    pasta_idx = os.path.join(pasta_cliente, "HANTS_REPROJETADO", idx)
    for fp in glob.glob(os.path.join(pasta_idx, "*.tif")):
        parts    = os.path.basename(fp).replace('.tif', '').split('_')
        data_str = parts[-1]
        if data_str.isdigit() and len(data_str) == 8:
            datas_set.add(data_str)

datas_disponiveis = sorted(datas_set)   # YYYYMMDD em ordem cronologica
T = len(datas_disponiveis)
F = len(indices_processados)
print(f"[OK] {T} periodos | {F} indices")
print(f"     {datas_disponiveis[0]} -> {datas_disponiveis[-1]}")
print(f"     Ordem dos indices: {indices_processados}")

# =====================================================================
# 6. DATACUBE IV: (T, H, W, F)  normalizado [0,1]
#
#    dc_iv[t, :, :, f] = indice f no periodo t
#    Todos os indices do mesmo periodo estao em dc_iv[t]
#    A ordem de f e sempre a de indices_processados
# =====================================================================
# Calcular o range esperado por indice a partir dos hiperparametros do HANTS
# Usado para detectar imagens "planas" (todos os pixeis no limiar low)
hants_hip = config.get('hants', {}).get('hiperparametros_indices', {})
ranges_esperados = {}
for nome_idx in indices_processados:
    hip = hants_hip.get(nome_idx, {})
    low_v  = float(hip.get('low',  0.0))
    high_v = float(hip.get('high', 1.0))
    ranges_esperados[nome_idx] = high_v - low_v

print("\n-> Preenchendo datacube IV (T, H, W, F) — normalizacao por imagem...")
print("   (cada imagem [mes x indice] normalizada pelo seu proprio min/max espacial)")
print("   Imagens com amplitude espacial < 2% do range do indice sao marcadas NaN")
print("   (evita amplificacao de ruido em periodos sem cobertura vegetal)")

# Inicializar com NaN — pixeis sem dados permanecem NaN
dc_iv   = np.full((T, h_ref, w_ref, F), np.nan, dtype=np.float32)
n_erros = 0

for f_idx, nome_idx in enumerate(indices_processados):
    pasta_idx       = os.path.join(pasta_cliente, "HANTS_REPROJETADO", nome_idx)
    range_esperado  = ranges_esperados.get(nome_idx, 1.0)
    # Limiar minimo de variabilidade: 2% do range total do indice
    min_amplitude   = 0.02 * range_esperado
    n_ok, n_miss, n_plano, n_err = 0, 0, 0, 0

    for t_idx, data_str in enumerate(datas_disponiveis):
        fp = os.path.join(pasta_idx, f"{nome_idx}_HANTS_{data_str}.tif")

        if not os.path.exists(fp):
            n_miss += 1
            continue   # gap temporal — fica NaN

        try:
            arr, nd = ler_e_alinhar(fp)

            # Mascara de nodata
            mascara_nd = (arr == nd) | ~np.isfinite(arr)
            validos    = arr[~mascara_nd]

            if validos.size == 0:
                n_miss += 1
                continue

            v_min = float(validos.min())
            v_max = float(validos.max())
            amplitude = v_max - v_min

            # Normalizacao Min-Max por imagem (mes x indice)
            if amplitude < min_amplitude:
                # Imagem "plana": todos os pixeis no limiar low (entressafra).
                # Normalizar por min/max local produziria 0.5 constante ou
                # amplificaria ruido numerico de ponto flutuante para [0,1].
                # Usamos 0.0 para todos os pixeis validos: indica ao autoencoder
                # que este periodo nao tem variabilidade espacial util (sem vegetacao).
                arr_norm = np.zeros((h_ref, w_ref), dtype=np.float32)
                n_plano += 1
            else:
                arr_norm = (arr - v_min) / amplitude

            arr_norm[mascara_nd] = np.nan

            # Inserir no datacube na posicao (periodo t, indice f)
            dc_iv[t_idx, :, :, f_idx] = arr_norm
            n_ok += 1

        except Exception as e:
            n_erros += 1
            n_err   += 1

    status = f"ok={n_ok}"
    if n_plano: status += f" | plano(NaN)={n_plano}"
    if n_miss:  status += f" | gap={n_miss}"
    if n_err:   status += f" | ERRO={n_err}"
    print(f"  [{f_idx}] {nome_idx:10s}  {status}")

# =====================================================================
# 7. GUARDAR DATACUBE IV + METADADOS
# =====================================================================
path_iv      = os.path.join(pasta_saida_dc, f"IV_{nome_cliente}_norm01.npy")
path_iv_feat = path_iv.replace('.npy', '_feature_names.txt')
path_iv_time = path_iv.replace('.npy', '_time_labels.txt')

np.save(path_iv, dc_iv)

with open(path_iv_feat, 'w') as f:
    # Ordem canonica dos indices (corresponde ao eixo F do datacube)
    f.write('\n'.join(indices_processados))

with open(path_iv_time, 'w') as f:
    # Datas YYYYMMDD em ordem cronologica (correspondem ao eixo T do datacube)
    f.write('\n'.join(datas_disponiveis))

# =====================================================================
# 8. RELATORIO FINAL
# =====================================================================
nan_global   = float(np.isnan(dc_iv).mean()) * 100
nan_por_feat = [float(np.isnan(dc_iv[:,:,:,f]).mean())*100 for f in range(F)]

print(f"\n[OK] Datacube IV guardado: shape={dc_iv.shape}  (T={T}, H={h_ref}, W={w_ref}, F={F})")
print(f"     NaN global: {nan_global:.1f}%")
for f, nome in enumerate(indices_processados):
    print(f"     [{f}] {nome:10s}  NaN={nan_por_feat[f]:.1f}%")
if n_erros > 0:
    print(f"     [AVISO] {n_erros} leitura(s) falharam — slots ficam NaN.")

print(f"\n     Ficheiros gerados:")
print(f"       {path_iv}")
print(f"       {path_iv_feat}")
print(f"       {path_iv_time}")
if mapas_topo:
    print(f"       {path_topo}")
    print(f"       {path_topo.replace('.npy','_feature_names.txt')}")

print("\n[CONCLUIDO] Modulo 3 finalizado com sucesso.")
