"""
configurar_ambiente.py --
Le variaveis de ambiente Docker e aplica-as ao config.json antes do pipeline arrancar.

Variaveis de ambiente suportadas:
  CLIENTE_NOME       Nome da fazenda/cliente (ex: "Fazenda_A_Group")
  NOME_AREA          Nome da area especifica dentro do cliente (ex: "fazenda_A", "fazenda_B")
                     Quando definido:
                       - pasta_destino  -> .../clientes/CLIENTE_NOME/areas/NOME_AREA/
                       - pasta_datacube -> .../clientes/CLIENTE_NOME/DATACUBE/  (partilhada)
                       - caminho_shp    -> .../areas/NOME_AREA/inputs/SHP_FILENAME
                       - nome (config)  -> NOME_AREA  (usado no nome dos ficheiros .npy)
  SHP_FILENAME       Nome do ficheiro shapefile em .../inputs/  (padrao: contorno_fazenda.shp)
  SRC_PROJETO        CRS do projeto em formato EPSG (ex: "EPSG:32723")
  DATA_INICIO        Data de inicio (ex: "2022-01-01")
  DATA_FIM           Data de fim    (ex: "2025-12-31")
  FREQUENCIA         "mensal" ou "semanal"
  MESES_SAFRA        Meses separados por virgula (ex: "10,11,12,1") ou vazio = todos
  COPERNICUS_USER    Email Copernicus Data Space
  COPERNICUS_PASS    Password Copernicus Data Space
  PARAR_APOS_MODULO  Para o pipeline apos o modulo indicado: 0=topografia, 1=download,
                     2=HANTS, 3=datacube. Omitir ou "todos" para correr tudo.

Estrutura de diretorios no HD:
  Seu_HD/                          <-> /dados/
    clientes/
      Fazenda_A_Group/
        DATACUBE/                      <- datacubes de TODAS as areas (partilhado)
          IV_fazendaA_norm01.npy
          IV_fazendaB_norm01.npy
          Estatico_fazendaC_norm01.npy
          ...
        areas/
          fazenda_A/
            inputs/                    <- shapefile da area
            TOPOGRAFIA/
            NDVI/, NDRE/, ...
            HANTS/
            HANTS_REPROJETADO/
          fazenda_B/
            inputs/
            ...

Exemplos:
  # Processar area "Fazenda_A" do cliente "Fazenda_A_Group"
  docker run -v "D:\\SEU_HD:/dados" \
    -e CLIENTE_NOME=Fazenda_A_Group \
    -e NOME_AREA=fazenda_A \
    -e SHP_FILENAME=fazenda_A.shp \
    -e SRC_PROJETO=EPSG:SEU_SRC \
    -e COPERNICUS_USER=email@email.com \
    -e COPERNICUS_PASS=senha \

  # Parar apos download para auditoria
  docker run -v "D:\\Seu_HD:/dados" \
    -e CLIENTE_NOME=Fazenda_A_Group -e NOME_AREA=fazenda_A \
    -e PARAR_APOS_MODULO=1 \
    -e COPERNICUS_USER=email@email.com -e COPERNICUS_PASS=senha \
"""
import os
import json
import sys

CONFIG_PATH = '/app/config.json'

try:
    with open(CONFIG_PATH) as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"ERRO CRITICO: {CONFIG_PATH} nao encontrado.")
    sys.exit(1)

mudancas = []

# =============================================================================
# CLIENTE / AREA
# =============================================================================
cliente_nome = os.getenv('CLIENTE_NOME')
nome_area    = os.getenv('NOME_AREA')
shp_file     = os.getenv('SHP_FILENAME', 'contorno_fazenda.shp')

if cliente_nome and nome_area:
    # Modo multi-area: cada area tem a sua pasta; DATACUBE e partilhado ao nivel do cliente
    pasta_cliente  = f"/dados/clientes/{cliente_nome}"
    pasta_area     = f"{pasta_cliente}/areas/{nome_area}"
    pasta_datacube = f"{pasta_cliente}/DATACUBE"

    config['cliente']['nome']               = nome_area          # nomeia os .npy pela area
    config['cliente']['pasta_destino']       = pasta_area
    config['cliente']['pasta_saida_datacube'] = pasta_datacube
    config['topografia']['pasta_inputs_qgis'] = f"{pasta_area}/TOPOGRAFIA"
    config['parametros_gerais']['caminho_shp'] = f"{pasta_area}/inputs/{shp_file}"

    mudancas.append(f"  cliente.nome              -> {nome_area}  (area)")
    mudancas.append(f"  cliente.pasta_destino     -> {pasta_area}")
    mudancas.append(f"  cliente.pasta_saida_datacube -> {pasta_datacube}")
    mudancas.append(f"  topografia.pasta          -> {pasta_area}/TOPOGRAFIA")
    mudancas.append(f"  caminho_shp               -> {pasta_area}/inputs/{shp_file}")

elif cliente_nome:
    # Modo cliente simples (uma unica area, sem subpasta areas/)
    pasta_base = f"/dados/clientes/{cliente_nome}"
    config['cliente']['nome']               = cliente_nome
    config['cliente']['pasta_destino']       = pasta_base
    config['cliente'].pop('pasta_saida_datacube', None)   # usa padrao (dentro de pasta_destino)
    config['topografia']['pasta_inputs_qgis'] = f"{pasta_base}/TOPOGRAFIA"
    config['parametros_gerais']['caminho_shp'] = f"{pasta_base}/inputs/{shp_file}"

    mudancas.append(f"  cliente.nome              -> {cliente_nome}")
    mudancas.append(f"  cliente.pasta_destino     -> {pasta_base}")
    mudancas.append(f"  caminho_shp               -> {pasta_base}/inputs/{shp_file}")

elif nome_area:
    # NOME_AREA sem CLIENTE_NOME: apenas atualiza o nome e o shapefile
    pasta_base = config['cliente']['pasta_destino']
    config['cliente']['nome'] = nome_area
    config['parametros_gerais']['caminho_shp'] = f"{pasta_base}/inputs/{shp_file}"
    mudancas.append(f"  cliente.nome              -> {nome_area}")

elif os.getenv('SHP_FILENAME'):
    pasta_base = config['cliente']['pasta_destino']
    config['parametros_gerais']['caminho_shp'] = f"{pasta_base}/inputs/{shp_file}"
    mudancas.append(f"  caminho_shp               -> {pasta_base}/inputs/{shp_file}")

# =============================================================================
# PARAMETROS GERAIS
# =============================================================================
if os.getenv('SRC_PROJETO'):
    config['parametros_gerais']['src_projeto'] = os.getenv('SRC_PROJETO')
    mudancas.append(f"  src_projeto               -> {os.getenv('SRC_PROJETO')}")

if os.getenv('DATA_INICIO'):
    config['download']['data_inicio'] = os.getenv('DATA_INICIO')
    mudancas.append(f"  data_inicio               -> {os.getenv('DATA_INICIO')}")

if os.getenv('DATA_FIM'):
    config['download']['data_fim'] = os.getenv('DATA_FIM')
    mudancas.append(f"  data_fim                  -> {os.getenv('DATA_FIM')}")

# =============================================================================
# FREQUENCIA
# =============================================================================
if os.getenv('FREQUENCIA'):
    freq = os.getenv('FREQUENCIA').strip().lower()
    if freq not in ('mensal', 'semanal'):
        print(f"  [AVISO] FREQUENCIA='{freq}' invalida. Aceites: 'mensal' ou 'semanal'.")
    else:
        config['download']['frequencia'] = freq
        mudancas.append(f"  frequencia               -> {freq}")

# =============================================================================
# MESES DA SAFRA
# =============================================================================
if os.getenv('MESES_SAFRA') is not None:
    raw = os.getenv('MESES_SAFRA').strip()
    if raw == '':
        config['download']['meses_safra'] = []
        mudancas.append("  meses_safra              -> [] (todos os meses)")
    else:
        try:
            meses     = [int(m.strip()) for m in raw.split(',') if m.strip()]
            invalidos = [m for m in meses if not (1 <= m <= 12)]
            if invalidos:
                print(f"  [AVISO] Meses invalidos em MESES_SAFRA: {invalidos}. A ignorar.")
            else:
                config['download']['meses_safra'] = meses
                mudancas.append(f"  meses_safra              -> {meses}")
        except ValueError:
            print("  [AVISO] MESES_SAFRA formato invalido. Esperado: '10,11,12,1'.")

# =============================================================================
# CREDENCIAIS COPERNICUS
# =============================================================================
if os.getenv('COPERNICUS_USER'):
    config['copernicus']['usuario'] = os.getenv('COPERNICUS_USER')
    mudancas.append("  copernicus_user          -> [env]")

if os.getenv('COPERNICUS_PASS'):
    config['copernicus']['senha'] = os.getenv('COPERNICUS_PASS')
    mudancas.append("  copernicus_pass          -> [env]")

# =============================================================================
# PARAR_APOS_MODULO (passado ao executar_pipeline.sh via config)
# =============================================================================
parar = os.getenv('PARAR_APOS_MODULO', '').strip()
if parar and parar not in ('', 'todos'):
    config['_parar_apos_modulo'] = parar
    mudancas.append(f"  parar_apos_modulo        -> {parar}")
else:
    config.pop('_parar_apos_modulo', None)

# =============================================================================
# GUARDAR
# =============================================================================
with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print("=== Configuracao do Ambiente ===")
if mudancas:
    for m in mudancas:
        print(m)
else:
    print("Nenhuma variavel definida. A usar config.json padrao.")
print("")
