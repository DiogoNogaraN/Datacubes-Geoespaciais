import os
import json
import glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rasterio

print("--- Auditoria Modulo 2: Series Temporais HANTS ---")

with open("config.json") as f:
    config = json.load(f)

pasta_cliente    = config["cliente"]["pasta_destino"]
indices          = config["download"]["indices"]
pasta_previews   = os.path.join(pasta_cliente, "PREVIEWS", "modulo2")
os.makedirs(pasta_previews, exist_ok=True)

for indice in indices:
    pasta_bruto  = os.path.join(pasta_cliente, indice)
    pasta_hants  = os.path.join(pasta_cliente, "HANTS_REPROJETADO", indice)

    arqs_brutos = sorted(glob.glob(os.path.join(pasta_bruto, "*.tif")))
    arqs_hants  = sorted(glob.glob(os.path.join(pasta_hants,  "*.tif")))

    if not arqs_brutos or not arqs_hants:
        print(f"  [AVISO] {indice}: imagens brutas ou HANTS ausentes. Pulando.")
        continue

    # -- Serie temporal do pixel central --
    def extrair_serie(arquivos):
        serie, datas = [], []
        for f in arquivos:
            with rasterio.open(f) as src:
                dados = src.read(1).astype(np.float32)
                nodata = src.nodata
                if nodata is not None:
                    dados[dados == nodata] = np.nan
                else:
                    dados[~np.isfinite(dados)] = np.nan
                cy, cx = dados.shape[0] // 2, dados.shape[1] // 2
                serie.append(float(np.nanmean(dados[max(0,cy-2):cy+3, max(0,cx-2):cx+3])))
            datas.append(os.path.basename(f))
        return datas, serie

    datas_b, serie_b = extrair_serie(arqs_brutos)
    datas_h, serie_h = extrair_serie(arqs_hants)

    # -- Figura 1: serie temporal --
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.scatter(range(len(serie_b)), serie_b, color="tomato",   s=30, label="Bruto",       zorder=3)
    ax.plot(   range(len(serie_h)), serie_h, color="steelblue", lw=2,  label="HANTS", zorder=2)
    ax.set_title(f"{indice} | Serie temporal pixel central (media 5x5)")
    ax.set_xlabel("Periodo")
    ax.set_ylabel(indice)
    ax.legend()
    xticks = range(0, len(datas_b), max(1, len(datas_b) // 12))
    ax.set_xticks(list(xticks))
    ax.set_xticklabels([datas_b[i][:10] for i in xticks], rotation=45, ha="right", fontsize=7)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(pasta_previews, f"{indice}_serie_temporal.png"), dpi=100, bbox_inches="tight")
    plt.close()

    # -- Figura 2: mapa antes/depois (primeira data disponivel) --
    arq_b_ref = arqs_brutos[len(arqs_brutos) // 2]   # data do meio
    nome_ref   = os.path.basename(arq_b_ref)
    # tentar encontrar o correspondente HANTS
    arq_h_ref  = arqs_hants[min(len(arqs_hants) // 2, len(arqs_hants) - 1)]

    with rasterio.open(arq_b_ref) as s:
        bruto = s.read(1).astype(np.float32)
        nodata = s.nodata
        if nodata is not None: bruto[bruto == nodata] = np.nan
        else: bruto[~np.isfinite(bruto)] = np.nan
    with rasterio.open(arq_h_ref) as s:
        hants = s.read(1).astype(np.float32)
        nodata = s.nodata
        if nodata is not None: hants[hants == nodata] = np.nan
        else: hants[~np.isfinite(hants)] = np.nan

    vmin = np.nanpercentile(np.concatenate([bruto[np.isfinite(bruto)], hants[np.isfinite(hants)]]), 2)
    vmax = np.nanpercentile(np.concatenate([bruto[np.isfinite(bruto)], hants[np.isfinite(hants)]]), 98)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    fig.suptitle(f"{indice} | Comparacao Bruto vs HANTS (data: {nome_ref[:10]})", fontsize=10)
    for ax, dados, titulo in zip(axes, [bruto, hants], ["Bruto (original)", "HANTS (suavizado)"]):
        im = ax.imshow(dados, cmap="RdYlGn", vmin=vmin, vmax=vmax)
        ax.set_title(titulo); ax.axis("off")
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    plt.savefig(os.path.join(pasta_previews, f"{indice}_mapa_comparacao.png"), dpi=100, bbox_inches="tight")
    plt.close()

    print(f"  [OK] {indice} -> serie + mapa comparacao")

print(f"\n[OK] Auditoria 2 concluida. Previews em: {pasta_previews}/")
print("     Verifique as series temporais para confirmar que o HANTS captura")
print("     o padrao fenologico sem sobre-suavizar. Ajuste hants.hiperparametros_indices")
print("     em config.json se necessario.")
