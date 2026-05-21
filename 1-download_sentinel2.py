import os
import json
import shutil
from datetime import datetime, timedelta
import requests
import openeo
import geopandas as gpd
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

print("Iniciando o script de Download automatizado e inteligente...")

# =====================================================================
# ETAPA 1: LER AS CONFIGURAÇÕES
# =====================================================================
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
    print("Configurações carregadas com sucesso!")
except FileNotFoundError:
    print("ERRO: Ficheiro config.json não encontrado.")
    exit(1)

# Extrair as variáveis básicas
nome_cliente = config['cliente']['nome']
pasta_destino_base = config['cliente']['pasta_destino']
caminho_shp = config['parametros_gerais']['caminho_shp']
data_inicio_str = config['download']['data_inicio']
data_fim_str = config['download']['data_fim']
indices_desejados = config['download']['indices'] 

# --- NOVAS VARIÁVEIS DE TEMPORALIDADE ---
# O .get() permite definir um valor padrão caso a variável não exista no ficheiro
frequencia       = config['download'].get('frequencia', 'mensal').lower()
meses_safra      = config['download'].get('meses_safra', [])
max_cloud        = config['download'].get('max_cloud_cover', 15)

copernicus_user = config['copernicus']['usuario']
copernicus_pass = config['copernicus']['senha']

start_date = datetime.strptime(data_inicio_str, "%Y-%m-%d")
end_date = datetime.strptime(data_fim_str, "%Y-%m-%d")

# =====================================================================
# ETAPA 2 e 3: PASTAS E AUTENTICAÇÃO 
# =====================================================================
os.makedirs(pasta_destino_base, exist_ok=True)

def autenticar_cdse(username: str, password: str) -> openeo.Connection:
    """
    Autentica no Copernicus Data Space via OIDC Resource Owner Password flow.

    Estratégia em camadas (compatível com qualquer versão do SDK openeo):
      1. Obter token Bearer diretamente do endpoint Keycloak via requests
      2. Injetar o token na sessão HTTP interna do openeo (_session ou request_session)
      3. Fallback: usar método nativo do SDK se disponível (versões mais antigas)
    """
    KEYCLOAK_URL = (
        "https://identity.dataspace.copernicus.eu"
        "/auth/realms/CDSE/protocol/openid-connect/token"
    )
    resp = requests.post(KEYCLOAK_URL, data={
        "grant_type": "password",
        "username":   username,
        "password":   password,
        "client_id":  "cdse-public",
    }, timeout=30)
    if not resp.ok:
        raise RuntimeError(
            f"Falha ao obter token CDSE (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    token = resp.json()["access_token"]

    conn = openeo.connect("openeo.dataspace.copernicus.eu")

    # Camada 1: injeção direta na sessão HTTP (openeo >= 0.20, atributo mais comum)
    if hasattr(conn, "_session"):
        conn._session.headers.update({"Authorization": f"Bearer {token}"})
    elif hasattr(conn, "request_session"):
        conn.request_session.headers.update({"Authorization": f"Bearer {token}"})
    else:
        # Camada 2: métodos nativos do SDK (versões mais antigas)
        for nome_metodo in [
            "authenticate_oidc_resource_owner_password_credentials",
            "authenticate_oidc_resource_owner_password",
        ]:
            if hasattr(conn, nome_metodo):
                getattr(conn, nome_metodo)(
                    client_id="cdse-public", username=username, password=password
                )
                print(f"  [INFO] Autenticado via SDK ({nome_metodo})")
                return conn
        raise RuntimeError(
            "Nenhum método de autenticação encontrado no SDK openeo instalado. "
            "Verifique a versão do pacote openeo em requirements.txt."
        )

    return conn

try:
    print("A conectar à plataforma Copernicus...")
    conn = autenticar_cdse(copernicus_user, copernicus_pass)
    print("Autenticação realizada com sucesso!")
except Exception as e:
    print(f"ERRO DE AUTENTICAÇÃO: {e}")
    exit(1)

# =====================================================================
# ETAPA 4: LEITURA DO SHAPEFILE E DEFINIÇÃO DA ÁREA (AOI)
# =====================================================================
# Usar a variável do config.json em vez do caminho fixo
aoi = gpd.read_file(caminho_shp)

print(f"INFO: CRS original do shapefile: {aoi.crs}")
aoi = aoi.to_crs(epsg=4326)
print(f"INFO: Shapefile convertido para CRS: {aoi.crs}")

aoi_union = aoi.geometry.union_all()

# Simplificar geometria para evitar erro 413 (payload demasiado grande na API OpenEO).
# Tolerância progressiva: tenta 0.0001° (~11m) primeiro; se ainda for pesada, usa convex_hull.
TOLERANCIA_INICIAL  = 0.0001   # graus  (~11 m)
LIMITE_GEOJSON_CHARS = 8_000   # caracteres (limite empírico seguro para o CDSE)

aoi_simplificada = aoi_union.simplify(TOLERANCIA_INICIAL, preserve_topology=True)
geojson_str = str(mapping(aoi_simplificada))

if len(geojson_str) > LIMITE_GEOJSON_CHARS:
    print(f"  [INFO] Geometria ainda grande ({len(geojson_str)} chars) após simplificação. A usar convex_hull.")
    aoi_simplificada = aoi_union.convex_hull

if not aoi_simplificada.is_valid:
    aoi_simplificada = aoi_simplificada.buffer(0)

aoi_geojson = mapping(aoi_simplificada)
print(f"INFO: Geometria AOI: {len(str(aoi_geojson))} chars (simplificada para API OpenEO)")

aoi_shapely_obj = aoi_simplificada

# Parâmetros (max_cloud lido do config.json na Etapa 1)
scale = 10
VERIFICAR_COBERTURA_AOI = True
PERCENTAGEM_MINIMA_COBERTURA = 95.0 
aoi_crs = "EPSG:4326"

# Função para calcular índices
def calcular_indices(datacube):
    ndvi = (datacube.band("B08") - datacube.band("B04")) / (datacube.band("B08") + datacube.band("B04"))
    ndre = (datacube.band("B08") - datacube.band("B05")) / (datacube.band("B08") + datacube.band("B05"))
    ndwi1 = (datacube.band("B08") - datacube.band("B11")) / (datacube.band("B08") + datacube.band("B11"))
    ndwi2 = (datacube.band("B08") - datacube.band("B12")) / (datacube.band("B08") + datacube.band("B12"))
    lnc = ((datacube.band("B08") - datacube.band("B05")) / (datacube.band("B08") + datacube.band("B05"))) * 4.060 + 0.43
    mcari = ((datacube.band("B05") - datacube.band("B04") * 0.2 - datacube.band("B03")) * datacube.band("B05")) / datacube.band("B04")
    mcari1 = ((datacube.band("B08") - datacube.band("B04")) * 2.5 - (datacube.band("B08") - datacube.band("B03")) * 1.3) * 1.2
    gndvi = (datacube.band("B08") - datacube.band("B03")) / (datacube.band("B08") + datacube.band("B03"))
    gosavi = 1.16 * ((datacube.band("B08") - datacube.band("B03")) / (datacube.band("B08") + datacube.band("B03") + 0.16))
    return {
        "NDVI": ndvi, "NDRE": ndre, "NDWI1": ndwi1, "NDWI2": ndwi2, "LNC": lnc, "MCARI": mcari, "MCARI1": mcari1, "GNDVI": gndvi, "GOSAVI": gosavi
    }

try:
    from openeo.rest import OpenEoApiError
    from openeo.rest.job import JobFailedException
except ImportError:
    OpenEoApiError = Exception
    JobFailedException = Exception

# ==============================================================================
# ETAPA 5: O NOVO LOOP TEMPORAL INTELIGENTE
# ==============================================================================
current = start_date

while current < end_date:
    
    # 1. VERIFICAÇÃO DA SAFRA: Este mês interessa-nos?
    # Se a lista de meses não estiver vazia E o mês atual não estiver lá, avançamos 1 dia e ignoramos.
    if len(meses_safra) > 0 and current.month not in meses_safra:
        current += timedelta(days=1)
        continue

    # 2. DEFINIÇÃO DO PERÍODO (Semanal vs Mensal)
    start_of_period_str = current.strftime("%Y-%m-%d")
    
    if frequencia == "semanal":
        fim_periodo = current + timedelta(days=6) # 7 dias (ex: dia 1 a dia 7)
        proximo_inicio = current + timedelta(days=7)
        label_periodo = f"{current.strftime('%Y-%m-%d')}_a_{fim_periodo.strftime('%m-%d')}"
    else: # Mensal (Padrão)
        proximo_inicio = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        fim_periodo = proximo_inicio - timedelta(days=1)
        label_periodo = current.strftime("%Y-%m")

    # Garante que o fim do período não ultrapassa a data final global do projeto
    if fim_periodo > end_date:
        fim_periodo = end_date

    end_of_period_str = fim_periodo.strftime("%Y-%m-%d")
    temporal_extent = [start_of_period_str, end_of_period_str]

    print(f"\n🔄 Processando período: {label_periodo} (de {start_of_period_str} até {end_of_period_str})...")

    # --- PROCESSAMENTO ---
    try:
        # A API do OpenEO recebe as nossas datas flexíveis
        datacube_para_processar = conn.load_collection(
            "SENTINEL2_L2A", 
            spatial_extent=aoi_geojson, 
            temporal_extent=temporal_extent, 
            bands=["B03", "B04", "B05", "B08", "B11", "B12"], 
            max_cloud_cover=max_cloud
        )
        
        # Reduz a dimensão temporal tirando a média das imagens daquele período (semana ou mês)
        # Nota: usar lambda em vez de string "mean" para compatibilidade com todas as versões do SDK
        datacube_reduzido = datacube_para_processar.reduce_dimension(
            dimension="t", reducer=lambda data: data.mean()
        )
        indices_calculados = calcular_indices(datacube_reduzido)

        for nome_indice, banda_indice in indices_calculados.items():
            if nome_indice not in indices_desejados: continue
            
            pasta_indice = os.path.join(pasta_destino_base, nome_indice)
            os.makedirs(pasta_indice, exist_ok=True)
            
            # O nome do ficheiro agora mostra se é mês ou semana
            nome_ficheiro_tif = f"{nome_indice}_{label_periodo}.tif"
            caminho_ficheiro_tif = os.path.join(pasta_indice, nome_ficheiro_tif)

            if os.path.exists(caminho_ficheiro_tif):
                print(f"   ⏭️ {nome_ficheiro_tif} já existe. Pulando.")
                continue

            print(f"   📥 Baixando {nome_ficheiro_tif}...")
            resultado_job = banda_indice.save_result(format="GTiff")
            job = resultado_job.create_job(title=nome_ficheiro_tif)
            job.start_and_wait()

            ficheiros_baixados = job.get_results().download_files(target=pasta_indice)
            ficheiro_tif_baixado = next((f for f in ficheiros_baixados if str(f).lower().endswith(".tif")), None)

            if ficheiro_tif_baixado:
                shutil.move(str(ficheiro_tif_baixado), caminho_ficheiro_tif)
                print(f"   ✅ Sucesso.")

    except Exception as e:
        # Quando não há imagens na semana devido a nuvens, a API pode dar erro. O script continua.
        print(f"   ❌ Erro ou sem imagens no período {label_periodo}: {e}")

    finally:
        # Avanca o "relogio" para a proxima semana ou proximo mes
        current = proximo_inicio

# =====================================================================
# ETAPA 6: VERIFICAÇÃO E PREENCHIMENTO DE LACUNAS (GAP-FILLING)
# Garante que todos os índices têm exactamente os mesmos períodos.
# =====================================================================
import calendar

def label_para_temporal_extent(label: str, freq: str):
    """
    Reconstrói o temporal_extent [inicio, fim] a partir do label do ficheiro.
      Mensal  : "2022-01"              -> ["2022-01-01", "2022-01-31"]
      Semanal : "2022-01-03_a_01-09"  -> ["2022-01-03", "2022-01-09"]
    """
    if freq == "semanal":
        # formato: YYYY-MM-DD_a_MM-DD
        parts = label.split("_a_")
        start_str = parts[0]                      # "2022-01-03"
        year      = start_str[:4]
        end_str   = f"{year}-{parts[1]}"          # "2022-01-09"
        return [start_str, end_str]
    else:
        # formato: YYYY-MM
        ano, mes = int(label[:4]), int(label[5:7])
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        return [f"{ano:04d}-{mes:02d}-01", f"{ano:04d}-{mes:02d}-{ultimo_dia:02d}"]


print("\n\n[VERIFICAÇÃO] Conferindo consistência de imagens entre índices...")

# 1. Recolher labels presentes por índice
labels_por_indice = {}
for indice in indices_desejados:
    pasta = os.path.join(pasta_destino_base, indice)
    if not os.path.isdir(pasta):
        labels_por_indice[indice] = set()
        continue
    prefixo = f"{indice}_"
    labels = set()
    for f in os.listdir(pasta):
        if f.endswith(".tif") and f.startswith(prefixo):
            labels.add(f[len(prefixo):-4])   # remove prefixo e ".tif"
    labels_por_indice[indice] = labels

# 2. Conjunto de referência = união de todos os labels encontrados
todos_labels = set()
for labels in labels_por_indice.values():
    todos_labels |= labels

if not todos_labels:
    print("  [AVISO] Nenhum ficheiro encontrado para gap-filling. Ignorando.")
else:
    # Relatório resumido
    for indice in indices_desejados:
        faltam = todos_labels - labels_por_indice[indice]
        total  = len(todos_labels)
        tem    = len(labels_por_indice[indice])
        print(f"  {indice:10s}: {tem}/{total} imagens  {'[OK]' if not faltam else f'[FALTA {len(faltam)}]'}")

    # 3. Re-descarregar os pares (índice, label) em falta
    pares_em_falta = [
        (indice, label)
        for indice in indices_desejados
        for label in sorted(todos_labels - labels_por_indice[indice])
    ]

    if not pares_em_falta:
        print("  [OK] Todos os índices têm o mesmo número de imagens.")
    else:
        print(f"\n  A re-descarregar {len(pares_em_falta)} par(es) em falta...")
        for indice, label in pares_em_falta:
            temporal_extent_gap = label_para_temporal_extent(label, frequencia)
            pasta_indice        = os.path.join(pasta_destino_base, indice)
            nome_ficheiro_tif   = f"{indice}_{label}.tif"
            caminho_ficheiro_tif = os.path.join(pasta_indice, nome_ficheiro_tif)

            if os.path.exists(caminho_ficheiro_tif):
                print(f"   ⏭️  {nome_ficheiro_tif} já existe (adicionado por outro processo). Pulando.")
                continue

            print(f"   📥 Gap-fill: {nome_ficheiro_tif}  [{temporal_extent_gap[0]} → {temporal_extent_gap[1]}]...")
            try:
                datacube_gap = conn.load_collection(
                    "SENTINEL2_L2A",
                    spatial_extent=aoi_geojson,
                    temporal_extent=temporal_extent_gap,
                    bands=["B03", "B04", "B05", "B08", "B11", "B12"],
                    max_cloud_cover=max_cloud,
                )
                datacube_gap = datacube_gap.reduce_dimension(
                    dimension="t", reducer=lambda data: data.mean()
                )
                indices_gap = calcular_indices(datacube_gap)
                banda_gap   = indices_gap[indice]

                resultado_gap = banda_gap.save_result(format="GTiff")
                job_gap       = resultado_gap.create_job(title=nome_ficheiro_tif)
                job_gap.start_and_wait()

                ficheiros_gap = job_gap.get_results().download_files(target=pasta_indice)
                ficheiro_gap  = next((f for f in ficheiros_gap if str(f).lower().endswith(".tif")), None)
                if ficheiro_gap:
                    shutil.move(str(ficheiro_gap), caminho_ficheiro_tif)
                    print(f"   ✅ Gap-fill concluído: {nome_ficheiro_tif}")
                else:
                    print(f"   ⚠️  Download concluído mas TIF não encontrado para {nome_ficheiro_tif}")

            except Exception as e:
                print(f"   ❌ Erro no gap-fill de {nome_ficheiro_tif}: {e}")

        print("\n  [VERIFICAÇÃO FINAL] Contagem após gap-filling:")
        for indice in indices_desejados:
            pasta   = os.path.join(pasta_destino_base, indice)
            prefixo = f"{indice}_"
            count   = sum(1 for f in os.listdir(pasta) if f.endswith(".tif") and f.startswith(prefixo)) if os.path.isdir(pasta) else 0
            print(f"    {indice:10s}: {count} imagens")

print("\n\n[OK] Processamento e Download concluidos com sucesso!\n")
