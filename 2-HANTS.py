import os
import json
import glob
import sys
import shutil
import rasterio
import rasterio.mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
import geopandas as gpd
import numpy as np
import pandas as pd

# Garante que o Python encontra o hants_main_runner clonado pelo Docker
sys.path.insert(0, '/app/hants')
from hants_main_runner import run_HANTS

print("--- Iniciando Modulo 2: Reprojecao, Recorte, HANTS ---")

# =====================================================================
# ETAPA 1: LER AS CONFIGURACOES
# =====================================================================
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print("ERRO CRITICO: Ficheiro config.json nao encontrado.")
    exit(1)

pasta_cliente          = config['cliente']['pasta_destino']
caminho_shp            = config['parametros_gerais']['caminho_shp']
src_destino            = config['parametros_gerais']['src_projeto']
indices_para_processar = config['download']['indices']
datas_remover          = config.get('limpeza', {}).get('datas_para_remover', [])
data_inicio            = config['download']['data_inicio']
data_fim               = config['download']['data_fim']
frequencia             = config['download'].get('frequencia', 'mensal')
nf_hants_config        = config['hants'].get('nf_padrao', 4)
fet_config             = config['hants'].get('fet_padrao', 0.1)
hiperparametros_hants  = config['hants'].get('hiperparametros_indices', {})

try:
    aoi_gdf = gpd.read_file(caminho_shp)
    print(f"Geometria carregada. SRC de destino: {src_destino}")
except Exception as e:
    print(f"ERRO ao ler o shapefile: {e}")
    exit(1)

# AOI reprojetada para o CRS de destino (metros) -- usada no recorte e no HANTS
aoi_utm    = aoi_gdf.to_crs(src_destino)
bounds_utm = aoi_utm.total_bounds          # [minx, miny, maxx, maxy]  em metros

# latlim/lonlim em metros (UTM) -- cellsize=10.0 fica correcto
latlim_hants = [float(bounds_utm[1]), float(bounds_utm[3])]
lonlim_hants = [float(bounds_utm[0]), float(bounds_utm[2])]
print(f"Grade HANTS (UTM, metros): Y=[{latlim_hants[0]:.1f}, {latlim_hants[1]:.1f}]  X=[{lonlim_hants[0]:.1f}, {lonlim_hants[1]:.1f}]")

# =====================================================================
# ETAPA 2: FUNCAO AUXILIAR -- REPROJECAO + RECORTE NUM UNICO PASSO
# =====================================================================
def reprojetar_e_recortar(input_path, output_path, dst_crs, geometrias_clip):
    """
    Reprojeta o raster para dst_crs e recorta com a geometria fornecida
    (ja em dst_crs). Guarda o resultado em output_path.
    """
    with rasterio.open(input_path) as src:
        transform_dst, width_dst, height_dst = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        perfil = src.meta.copy()
        perfil.update({
            'crs':       dst_crs,
            'transform': transform_dst,
            'width':     width_dst,
            'height':    height_dst,
        })
        # Reprojectar para MemoryFile
        with rasterio.io.MemoryFile() as memfile:
            with memfile.open(**perfil) as mem:
                for i in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(mem, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform_dst,
                        dst_crs=dst_crs,
                        resampling=Resampling.cubic,  # cubic suaviza costuras entre tiles S2
                    )
                # Recortar em UTM
                out_image, out_transform = rasterio.mask.mask(
                    mem, geometrias_clip, crop=True
                )
                perfil_clip = mem.profile.copy()
                perfil_clip.update({
                    'height':    out_image.shape[1],
                    'width':     out_image.shape[2],
                    'transform': out_transform,
                    'compress':  'lzw',
                })
                with rasterio.open(output_path, 'w', **perfil_clip) as dst:
                    dst.write(out_image)

geometrias_utm = [geom for geom in aoi_utm.geometry]

# =====================================================================
# FUNCAO AUXILIAR -- DETECCAO AUTOMATICA DE IMAGENS PROBLEMATICAS
# =====================================================================
def detectar_imagens_problematicas(pasta_utm, indice, low, high,
                                   fill_val=-9999.0,
                                   min_cobertura=0.30,
                                   max_fora_intervalo=0.50,
                                   max_zscore_mediana=2.5):
    """
    Analisa cada imagem TEMP_UTM e identifica aquelas com interferencias de
    nuvens, sombras ou artefactos, usando tres criterios independentes:

      1. Cobertura insuficiente  : pixels validos < min_cobertura
      2. Fora do intervalo valido: > max_fora_intervalo dos pixels validos
                                   estao fora de [low, high]
      3. Outlier temporal (MAD)  : mediana espacial da imagem esta a mais de
                                   max_zscore_mediana desvios (MAD-normalizado)
                                   da mediana temporal do conjunto

    Retorna: dict  {basename_do_ficheiro: motivo_de_exclusao}
    """
    arquivos = sorted(glob.glob(os.path.join(pasta_utm, "*.tif")))
    if not arquivos:
        return {}

    stats = []
    for fp in arquivos:
        nome = os.path.basename(fp)
        try:
            with rasterio.open(fp) as src:
                arr = src.read(1).astype(np.float32)
                nd  = src.nodata
            if nd is not None:
                arr[np.isclose(arr, float(nd))] = np.nan
            arr[np.isclose(arr, fill_val)] = np.nan
            arr[~np.isfinite(arr)]         = np.nan

            n_total = arr.size
            n_valid = int(np.sum(np.isfinite(arr)))
            cobertura = n_valid / n_total if n_total > 0 else 0.0

            if n_valid > 0:
                vals           = arr[np.isfinite(arr)]
                fora_intervalo = float(np.sum((vals < low) | (vals > high)) / len(vals))
                mediana_esp    = float(np.median(vals))
            else:
                fora_intervalo = 1.0
                mediana_esp    = np.nan

        except Exception as e:
            print(f"    [AVISO] Erro ao analisar {nome}: {e}")
            stats.append({'file': nome, 'cobertura': 0.0,
                          'fora_intervalo': 1.0, 'mediana_esp': np.nan})
            continue

        stats.append({'file': nome, 'cobertura': cobertura,
                      'fora_intervalo': fora_intervalo, 'mediana_esp': mediana_esp})

    excluir = {}

    # Criterio 1: Cobertura insuficiente
    for s in stats:
        if s['cobertura'] < min_cobertura:
            excluir[s['file']] = f"cobertura={s['cobertura']:.1%} < {min_cobertura:.0%}"

    # Criterio 2: Alta proporcao de pixels fora do intervalo valido
    for s in stats:
        if s['file'] not in excluir and s['fora_intervalo'] > max_fora_intervalo:
            excluir[s['file']] = f"fora_intervalo={s['fora_intervalo']:.1%} > {max_fora_intervalo:.0%}"

    # Criterio 3: Outlier temporal (MAD z-score da mediana espacial)
    medianas_ref = [
        s['mediana_esp'] for s in stats
        if s['file'] not in excluir and np.isfinite(s['mediana_esp'])
    ]
    if len(medianas_ref) >= 4:
        arr_med    = np.array(medianas_ref, dtype=np.float64)
        med_global = float(np.median(arr_med))
        mad        = float(np.median(np.abs(arr_med - med_global)))
        sigma_mad  = mad * 1.4826    # factor de escala MAD -> desvio padrao equivalente
        if sigma_mad > 1e-9:
            for s in stats:
                if s['file'] not in excluir and np.isfinite(s['mediana_esp']):
                    z = abs(s['mediana_esp'] - med_global) / sigma_mad
                    if z > max_zscore_mediana:
                        excluir[s['file']] = (
                            f"zscore_MAD={z:.2f} > {max_zscore_mediana} "
                            f"(med={s['mediana_esp']:.4f}, ref={med_global:.4f})"
                        )

    return excluir


# =====================================================================
# FUNCAO AUXILIAR -- MAIOR GAP TEMPORAL (para calculo dinamico do NF)
# =====================================================================
def calcular_maior_gap(pasta_utm, indice, data_inicio, data_fim, frequencia, excluir=None):
    """
    Percorre a serie temporal esperada (do date_range) e calcula o maior
    numero consecutivo de periodos sem imagem valida.

    Considera tanto ficheiros fisicamente ausentes como os excluidos pela
    deteccao automatica (parametro excluir).

    Retorna: int -- tamanho do maior gap em periodos
    """
    freq_pd     = 'W-MON' if frequencia == 'semanal' else 'MS'
    datas       = pd.date_range(data_inicio, data_fim, freq=freq_pd)
    excluir_set = (set(excluir.keys()) if isinstance(excluir, dict)
                   else (set(excluir) if excluir else set()))

    max_gap   = 0
    gap_atual = 0

    for d in datas:
        if frequencia == 'semanal':
            padrao  = os.path.join(pasta_utm, f"{indice}_{d.strftime('%Y-%m-%d')}_a_*.tif")
            matches = glob.glob(padrao)
            valido  = bool(matches) and all(os.path.basename(m) not in excluir_set for m in matches)
        else:
            nome   = f"{indice}_{d.strftime('%Y-%m')}.tif"
            valido = (os.path.exists(os.path.join(pasta_utm, nome))
                      and nome not in excluir_set)

        if valido:
            gap_atual = 0
        else:
            gap_atual += 1
            if gap_atual > max_gap:
                max_gap = gap_atual

    return max_gap


# =====================================================================
# ETAPA 3 (PRE): DETECCAO POR CONSENSO -- antes do loop principal
#
# Nuvens afectam TODOS os indices da mesma data. Por isso a deteccao
# deve ser feita uma vez para todos os indices, e uma data so e excluida
# se for sinalizada em pelo menos min_votos_consenso indices.
# Isto garante que todos os indices partilham exactamente o mesmo
# conjunto de datas excluidas.
# =====================================================================
print(f"\n{'='*50}")
print(f"  PRE-ETAPA: DETECCAO POR CONSENSO")
print(f"{'='*50}")

config_autodet     = config.get('limpeza', {}).get('auto_detecao', {})
min_votos          = config_autodet.get('min_votos_consenso',
                        max(2, len(indices_para_processar) // 2))

votos_data  = {}   # data_label -> {indice: motivo}
excluir_raw = {}   # indice     -> {basename: motivo}

for ind in indices_para_processar:
    pasta_t = os.path.join(pasta_cliente, "TEMP_UTM", ind)
    p_ind   = hiperparametros_hants.get(ind, {"low": 0.0, "high": 1.0})

    if not os.path.isdir(pasta_t) or not glob.glob(os.path.join(pasta_t, "*.tif")):
        excluir_raw[ind] = {}
        continue

    det = detectar_imagens_problematicas(
        pasta_t, ind,
        low               = p_ind['low'],
        high              = p_ind['high'],
        min_cobertura     = config_autodet.get('min_cobertura',      0.15),
        max_fora_intervalo= config_autodet.get('max_fora_intervalo', 0.70),
        max_zscore_mediana= config_autodet.get('max_zscore_mediana', 3.0),
    )
    excluir_raw[ind] = det

    for basename, motivo in det.items():
        data_label = basename[len(ind) + 1 : -4]   # remove "INDICE_" e ".tif"
        if data_label not in votos_data:
            votos_data[data_label] = {}
        votos_data[data_label][ind] = motivo

# Datas que atingiram o quorum de consenso
datas_consenso = {
    d: votes for d, votes in votos_data.items()
    if len(votes) >= min_votos
}

print(f"  Limiar de consenso : {min_votos} / {len(indices_para_processar)} indices")
print(f"  Datas individuais sinalizadas : {len(votos_data)}")
print(f"  Datas excluidas por consenso  : {len(datas_consenso)}")
if datas_consenso:
    for d in sorted(datas_consenso):
        flagrados = list(datas_consenso[d].keys())
        print(f"    - {d}  (em {len(flagrados)} indices: {', '.join(flagrados)})")
else:
    print(f"    Nenhuma data excluida.")

# Mapa final de exclusao por indice (so datas do consenso, mesmo conjunto para todos)
excluir_por_indice = {}
for ind in indices_para_processar:
    excluir_por_indice[ind] = {
        f"{ind}_{d}.tif": excluir_raw[ind].get(f"{ind}_{d}.tif", "consenso")
        for d in datas_consenso
    }

# =====================================================================
# ETAPA 3: PROCESSAMENTO PRINCIPAL
# =====================================================================
for indice in indices_para_processar:
    print(f"\n{'='*50}\n PROCESSANDO INDICE: {indice}\n{'='*50}")

    pasta_input             = os.path.join(pasta_cliente, indice)
    pasta_temp_utm          = os.path.join(pasta_cliente, "TEMP_UTM", indice)
    pasta_output_hants      = os.path.join(pasta_cliente, "HANTS", indice)
    pasta_final_reprojetada = os.path.join(pasta_cliente, "HANTS_REPROJETADO", indice)

    os.makedirs(pasta_temp_utm,          exist_ok=True)
    os.makedirs(pasta_output_hants,      exist_ok=True)
    os.makedirs(pasta_final_reprojetada, exist_ok=True)

    arquivos_originais = glob.glob(os.path.join(pasta_input, "*.tif"))
    if not arquivos_originais:
        print(f"  [AVISO] Nenhuma imagem em {pasta_input}. Pulando.")
        continue

    # --- 3.1: Reprojecao para UTM + Recorte ---
    print(f" -> 1. Reprojetando para {src_destino} e recortando...")
    arquivos_validos = 0
    for filepath in sorted(arquivos_originais):
        filename = os.path.basename(filepath)

        if any(data_ruim in filename for data_ruim in datas_remover):
            print(f"    [REMOVIDO] {filename}")
            continue

        caminho_utm = os.path.join(pasta_temp_utm, filename)
        if os.path.exists(caminho_utm):
            arquivos_validos += 1
            continue  # ja processado numa execucao anterior

        try:
            reprojetar_e_recortar(filepath, caminho_utm, src_destino, geometrias_utm)
            arquivos_validos += 1
        except Exception as e:
            print(f"    [ERRO] {filename}: {e}")

    print(f"    {arquivos_validos} imagens prontas em {src_destino}")

    # --- 3.2: HANTS (imagens ja em UTM, cellsize em metros) ---
    if arquivos_validos == 0:
        print(f"  [AVISO] Sem imagens validas para HANTS. Pulando.")
        continue

    params  = hiperparametros_hants.get(indice, {"HiLo": "Lo", "low": 0.0, "high": 1.0, "dod": 1, "delta": 0.1})
    nc_path = os.path.join(pasta_cliente, "HANTS", f"{indice}_temp.nc")

    # --- Exclusao por consenso (calculada na pre-etapa, igual para todos os indices) ---
    excluir_auto = excluir_por_indice.get(indice, {})
    if excluir_auto:
        print(f" -> 2. Excluindo {len(excluir_auto)} data(s) por consenso: "
              f"{', '.join(sorted(excluir_auto.keys()))}")
    else:
        print(f" -> 2. Nenhuma data excluida por consenso.")

    # EPSG numerico para o NetCDF/GeoTIFF de saida
    epsg_num = int(src_destino.split(':')[-1])

    # Derivar latlim/lonlim DOS BOUNDS REAIS do raster TEMP_UTM (Fix: alinhamento pixel-a-pixel).
    # Usar os bounds do shapefile (AOI) como origem da grelha HANTS causava desalinhamento
    # sub-pixel que se manifestava como padrao quadriculado nos outputs.
    arquivos_utm_existentes = sorted(glob.glob(os.path.join(pasta_temp_utm, "*.tif")))
    with rasterio.open(arquivos_utm_existentes[0]) as src_ref:
        rb           = src_ref.bounds
        cellsize_ref = abs(src_ref.transform.a)   # resolucao real em metros
    latlim_hants = [float(rb.bottom), float(rb.top)]
    lonlim_hants = [float(rb.left),   float(rb.right)]
    print(f"    [INFO] Grade HANTS alinhada ao raster: "
          f"Y=[{latlim_hants[0]:.1f}, {latlim_hants[1]:.1f}]  "
          f"X=[{lonlim_hants[0]:.1f}, {lonlim_hants[1]:.1f}]  "
          f"px={cellsize_ref:.2f}m")

    # ni real = numero de slots de tempo que create_netcdf vai gerar
    freq_pd = 'W-MON' if frequencia == 'semanal' else 'MS'
    ni_real = len(pd.date_range(data_inicio, data_fim, freq=freq_pd))

    # nb = ni_real (cobre a serie COMPLETA, nao apenas um ano).
    # Com nb=12, todos os Janeiros de todos os anos recebem o mesmo angulo
    # harmonico -> saida identica em cada ano, eliminando variabilidade interanual.
    # Com nb=ni_real, cada mes de cada ano tem angulo unico: o HANTS captura
    # simultaneamente o ciclo anual e as tendencias interanuais.
    nb_hants = ni_real

    dod_val = params.get('dod', 1)

    # NF minimo para que o ciclo anual esteja representado dentro de nb=ni_real:
    # a harmonica anual tem frequencia ni_real/nb_anual onde nb_anual=12 (mensal)
    # ou nb_anual=52 (semanal). Arredondado ao inteiro mais proximo.
    nb_anual      = 52 if frequencia == 'semanal' else 12
    nf_min_anual  = max(1, round(ni_real / nb_anual))

    # NF dinamico: maior entre o gap-based e o minimo para capturar o ciclo anual.
    maior_gap  = calcular_maior_gap(
        pasta_temp_utm, indice, data_inicio, data_fim, frequencia, excluir=excluir_auto
    )
    nf_por_gap = max(1, maior_gap) if maior_gap > 0 else nf_min_anual
    nf_efetivo = min(max(nf_por_gap, nf_min_anual), nf_hants_config)
    print(f"    [INFO] ni={ni_real}  nb=ni  nf_min_anual={nf_min_anual}  "
          f"gap={maior_gap}  -> NF efectivo inicial = {nf_efetivo}")

    # Salvaguarda: reduzir nf se ni for insuficiente para noutmax >= 1
    # noutmax = ni - min(2*nf+1, ni) - dod >= 1
    noutmax = ni_real - min(2 * nf_efetivo + 1, ni_real) - dod_val
    if noutmax < 1:
        nf_efetivo = max(1, (ni_real - dod_val - 2) // 2)
        print(f"    [INFO] NF reduzido para {nf_efetivo} "
              f"(ni={ni_real} insuficiente com dod={dod_val})")

    print(f" -> 3. Executando HANTS (ni={ni_real}, nb={nb_hants}, NF={nf_efetivo}, "
          f"EPSG={epsg_num}, Freq={frequencia}, HiLo={params['HiLo']}, "
          f"Min={params['low']}, Max={params['high']})...")
    try:
        run_HANTS(
            rasters_path_inp=pasta_temp_utm,
            vi_name_for_files=indice,
            start_date=data_inicio,
            end_date=data_fim,
            latlim=latlim_hants,
            lonlim=lonlim_hants,
            cellsize=cellsize_ref,   # resolucao real do raster (garante alinhamento)
            nc_path=nc_path,
            nb=nb_hants,             # periodicidade anual (12 ou 52) -- correcto
            nf=nf_efetivo,
            HiLo=params['HiLo'],
            low=params['low'],
            high=params['high'],
            fet=fet_config,
            dod=dod_val,
            delta=params['delta'],
            rasters_path_out=pasta_output_hants,
            export_hants_only=True,
            frequencia=frequencia,
            epsg=epsg_num,
            excluir=excluir_auto,    # imagens problematicas detectadas automaticamente
        )
        if os.path.exists(nc_path):
            os.remove(nc_path)

    except Exception as e:
        print(f"    [ERRO CRITICO] Falha no HANTS para {indice}: {e}")
        import traceback; traceback.print_exc()
        continue

    # --- 3.3: Capping pos-HANTS --------------------------------------------------
    # O ajuste harmonico pode extrapolar ligeiramente fora de [low, high] por
    # efeito de Gibbs (oscilaçoes das harmonicas nas bordas da serie ou junto
    # a outliers). Garante que o output final fica estritamente dentro do
    # intervalo valido definido no config.
    print(f" -> 4. Capping pos-HANTS [{params['low']}, {params['high']}]...")
    arquivos_hants_out = glob.glob(os.path.join(pasta_output_hants, "*.tif"))
    n_px_clipped = 0
    for fp_out in arquivos_hants_out:
        fp_tmp = fp_out + ".tmp.tif"
        try:
            with rasterio.open(fp_out) as src:
                arr     = src.read(1).astype(np.float32)
                profile = src.profile.copy()
                nd_val  = float(src.nodata) if src.nodata is not None else -9999.0

            valido = np.isfinite(arr) & ~np.isclose(arr, nd_val)
            fora   = valido & ((arr < params['low']) | (arr > params['high']))
            n_fora = int(np.sum(fora))

            if n_fora > 0:
                arr[valido & (arr < params['low'])] = params['low']
                arr[valido & (arr > params['high'])] = params['high']
                # Escreve num ficheiro temporario e depois renomeia atomicamente
                # para evitar corrupcao por overwrting in-place de TIFFs comprimidos
                with rasterio.open(fp_tmp, 'w', **profile) as dst:
                    dst.write(arr, 1)
                os.replace(fp_tmp, fp_out)
                n_px_clipped += n_fora
        except Exception as e:
            print(f"    [AVISO] Capping falhou em {os.path.basename(fp_out)}: {e}")
            if os.path.exists(fp_tmp):
                os.remove(fp_tmp)

    if n_px_clipped > 0:
        print(f"    [INFO] {n_px_clipped} pixel(s) clipados para [{params['low']}, {params['high']}] "
              f"em {len(arquivos_hants_out)} imagens.")
    else:
        print(f"    [OK] Nenhum pixel fora do intervalo valido.")

    # --- 3.4: Copiar para HANTS_REPROJETADO (ja estao em UTM -- nao e necessaria reprojecao) ---
    print(f" -> 5. Copiando resultados para HANTS_REPROJETADO...")
    arquivos_hants = glob.glob(os.path.join(pasta_output_hants, "*.tif"))
    for filepath in arquivos_hants:
        filename = os.path.basename(filepath)
        destino  = os.path.join(pasta_final_reprojetada, filename)
        try:
            shutil.copy2(filepath, destino)
            print(f"    [OK] {filename}")
        except Exception as e:
            print(f"    [ERRO] {filename}: {e}")

print("\n--- Modulo 2 Finalizado! ---")
