import os
import json
import glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rasterio

print("--- Auditoria Modulo 1: Quicklooks pos-Download ---")

with open("config.json") as f:
    config = json.load(f)

pasta_cliente    = config["cliente"]["pasta_destino"]
indices          = config["download"]["indices"]
pasta_previews   = os.path.join(pasta_cliente, "PREVIEWS", "modulo1")
os.makedirs(pasta_previews, exist_ok=True)

resumo = []

for indice in indices:
    pasta_iv = os.path.join(pasta_cliente, indice)
    arquivos = sorted(glob.glob(os.path.join(pasta_iv, "*.tif")))
    if not arquivos:
        print(f"  [AVISO] Nenhum ficheiro encontrado para {indice}. Pulando.")
        continue

    n_imagens = len(arquivos)
    primeiro  = arquivos[0]
    nome_data = os.path.splitext(os.path.basename(primeiro))[0]

    with rasterio.open(primeiro) as src:
        dados = src.read(1).astype(np.float32)
        nodata = src.nodata

    if nodata is not None:
        dados[dados == nodata] = np.nan
    else:
        dados[~np.isfinite(dados)] = np.nan

    validos    = dados[np.isfinite(dados)]
    cobertura  = 100.0 * validos.size / dados.size if dados.size > 0 else 0.0
    v_min      = float(np.nanmin(validos)) if validos.size > 0 else float("nan")
    v_max      = float(np.nanmax(validos)) if validos.size > 0 else float("nan")
    v_med      = float(np.nanmean(validos)) if validos.size > 0 else float("nan")

    resumo.append(f"  {indice:8s}  {n_imagens:3d} imagens  cobertura={cobertura:.1f}%  "
                  f"min={v_min:.3f}  max={v_max:.3f}  media={v_med:.3f}")

    # -- figura: mapa + histograma --
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    fig.suptitle(f"{indice} | {nome_data} | {n_imagens} imagens disponiveis", fontsize=11)

    im = axes[0].imshow(dados, cmap="RdYlGn", vmin=np.nanpercentile(dados, 2), vmax=np.nanpercentile(dados, 98))
    axes[0].set_title("Primeira imagem disponivel")
    axes[0].axis("off")
    plt.colorbar(im, ax=axes[0], fraction=0.046, pad=0.04)

    axes[1].hist(validos[np.isfinite(validos)], bins=60, color="steelblue", edgecolor="none")
    axes[1].set_title(f"Distribuicao de valores  (cobertura={cobertura:.1f}%)")
    axes[1].set_xlabel(indice)
    axes[1].set_ylabel("Pixels")

    plt.tight_layout()
    saida = os.path.join(pasta_previews, f"{indice}_quicklook.png")
    plt.savefig(saida, dpi=100, bbox_inches="tight")
    plt.close()
    print(f"  [OK] {indice} -> {saida}")

print("\n--- Resumo por Indice ---")
for linha in resumo:
    print(linha)

# Salvar resumo em texto
with open(os.path.join(pasta_previews, "resumo_download.txt"), "w") as f:
    f.write("\n".join(resumo))

print(f"\n[OK] Auditoria 1 concluida. Previews em: {pasta_previews}/")
