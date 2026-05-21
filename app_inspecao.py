import streamlit as st
import os
import json
import glob
import rasterio
import rasterio.mask
import geopandas as gpd
import numpy as np
import matplotlib.cm as cm

# 1. CONFIGURAÇÃO DA PÁGINA WEB
st.set_page_config(layout="wide", page_title="Inspeção Agronómica")
st.title("🛰️ Triagem Visual de Imagens de Satélite")
st.markdown("Selecione as imagens com excesso de nuvens ou anomalias para as excluir antes da reconstrução HANTS.")

# 2. LER CONFIGURAÇÕES
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    st.error("Erro: Ficheiro config.json não encontrado!")
    st.stop()

pasta_cliente = config['cliente']['pasta_destino']
caminho_shp = config['parametros_gerais']['caminho_shp']
indices_para_processar = config['download']['indices']

# Se não existir a chave de limpeza no json, criamos uma vazia
if 'limpeza' not in config:
    config['limpeza'] = {"datas_para_remover": []}

datas_remover_atuais = config['limpeza'].get('datas_para_remover', [])

# 3. INTERFACE LATERAL (Sidebar)
st.sidebar.header("Controlos")
indice_selecionado = st.sidebar.selectbox("Selecione o Índice para Inspeção:", indices_para_processar)

# 4. CARREGAR A GEOMETRIA (Para recortar a imagem na hora e focar na fazenda)
@st.cache_data # O cache evita que o shapefile seja lido várias vezes
def carregar_geometria(caminho):
    return gpd.read_file(caminho)

aoi_gdf = carregar_geometria(caminho_shp)

# 5. LER E APRESENTAR AS IMAGENS
pasta_imagens = os.path.join(pasta_cliente, indice_selecionado)
arquivos = sorted(glob.glob(os.path.join(pasta_imagens, "*.tif")))

if not arquivos:
    st.warning(f"Nenhuma imagem encontrada para o índice {indice_selecionado}.")
    st.stop()

st.subheader(f"Galeria de Imagens: {indice_selecionado}")
st.write(f"Encontradas {len(arquivos)} imagens.")

# Definir colormap baseado no índice
cmap = cm.get_cmap('RdYlGn') if 'ND' in indice_selecionado else cm.get_cmap('viridis')

# Vamos armazenar as escolhas do utilizador
novas_datas_remover = []

# Criar uma grelha de 4 colunas
colunas_por_linha = 4
cols = st.columns(colunas_por_linha)

for i, filepath in enumerate(arquivos):
    filename = os.path.basename(filepath)
    # Extrair a data do nome (ex: assume formato INDICE_2024-03.tif)
    data_img = filename.split('_')[-1].replace('.tif', '')
    
    # Renderizar na coluna correta
    col = cols[i % colunas_por_linha]
    
    with col:
        st.markdown(f"**{data_img}**")
        
        try:
            # Recorte visual na hora da imagem
            with rasterio.open(filepath) as src:
                aoi_reprojected = aoi_gdf.to_crs(src.crs)
                out_image, _ = rasterio.mask.mask(src, aoi_reprojected.geometry, crop=True)
                
                img_array = out_image[0]
                
                # Normalizar para visualização (0 a 1)
                vmin, vmax = np.nanpercentile(img_array, 2), np.nanpercentile(img_array, 98)
                img_norm = np.clip((img_array - vmin) / (vmax - vmin), 0, 1)
                
                # Converter para cores (RGBA) para o Streamlit
                img_colorida = cmap(img_norm)
                
                # Mostrar a imagem
                st.image(img_colorida, use_column_width=True)
                
        except Exception as e:
            st.error(f"Erro ao ler imagem.")
            
        # Checkbox para remover (se a data já estava no config, aparece marcada)
        marcado = st.checkbox("Remover esta data", value=(data_img in datas_remover_atuais), key=filename)
        
        if marcado:
            if data_img not in novas_datas_remover:
                novas_datas_remover.append(data_img)

# 6. BOTÃO DE SALVAR
st.sidebar.markdown("---")
st.sidebar.subheader("Ação")
if st.sidebar.button("💾 Salvar Limpeza e Atualizar Configuração", use_container_width=True):
    # Atualizar o dicionário
    config['limpeza']['datas_para_remover'] = novas_datas_remover
    
    # Escrever de volta no ficheiro JSON
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
        
    st.sidebar.success("Configurações salvas com sucesso! Podes agora executar o Passo 2 (HANTS).")