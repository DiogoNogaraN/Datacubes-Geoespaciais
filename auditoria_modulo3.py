import os
import json
import numpy as np
import warnings
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

print("--- Auditoria Modulo 3: Validacao do Datacube ---")

with open("config.json") as f:
    config = json.load(f)

pasta_cliente  = config["cliente"]["pasta_destino"]
nome_cliente   = config["cliente"]["nome"]
pasta_saida_dc = config["cliente"].get("pasta_saida_datacube",
                     os.path.join(pasta_cliente, "DATACUBE"))
pasta_previews = os.path.join(pasta_cliente, "PREVIEWS", "modulo3")
os.makedirs(pasta_previews, exist_ok=True)

indices_iv     = config["download"]["indices"]
variaveis_topo = config["topografia"]["variaveis"]

# Suprimir avisos de nanmean/nanstd em pixeis fora da fazenda (NaN em todos os periodos)
warnings.filterwarnings("ignore", category=RuntimeWarning, message="Mean of empty slice")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="All-NaN slice")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="Degrees of freedom")

# =====================================================================
# 1. DATACUBE IV
# =====================================================================
path_iv      = os.path.join(pasta_saida_dc, f"IV_{nome_cliente}_norm01.npy")
path_iv_feat = path_iv.replace('.npy', '_feature_names.txt')
path_iv_time = path_iv.replace('.npy', '_time_labels.txt')

if not os.path.exists(path_iv):
    print(f"  [AVISO] Datacube IV nao encontrado: {path_iv}")
else:
    dc_iv = np.load(path_iv)
    T, H, W, F = dc_iv.shape

    feat_labels = (open(path_iv_feat).read().splitlines()
                   if os.path.exists(path_iv_feat) else [f"F{i}" for i in range(F)])
    time_labels = (open(path_iv_time).read().splitlines()
                   if os.path.exists(path_iv_time) else [str(t) for t in range(T)])
    # Labels abreviados para titulos de subplots: YYYYMM
    time_short  = [lbl[:4] + "-" + lbl[4:6] for lbl in time_labels]

    print(f"\n  Datacube IV:  shape={dc_iv.shape}  (T={T}, H={H}, W={W}, F={F})")
    print(f"  Periodo: {time_labels[0]} -> {time_labels[-1]}")

    nan_pct_tempo = 100.0 * np.isnan(dc_iv).sum(axis=(1,2,3)) / (H * W * F)
    nan_pct_feat  = 100.0 * np.isnan(dc_iv).sum(axis=(0,1,2)) / (T * H * W)
    xtick_step    = max(1, T // 12)

    # ------------------------------------------------------------------
    # Grafico 1: % NaN por periodo e por indice
    # ------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(15, 4))

    axes[0].bar(range(T), nan_pct_tempo, color="tomato")
    axes[0].set_xticks(range(0, T, xtick_step))
    axes[0].set_xticklabels(time_labels[::xtick_step], rotation=45, ha='right', fontsize=6)
    axes[0].set_title("% NaN por periodo temporal")
    axes[0].set_ylabel("% NaN")

    axes[1].bar(range(F), nan_pct_feat, tick_label=feat_labels[:F], color="steelblue")
    axes[1].set_title("% NaN por indice IV")
    axes[1].tick_params(axis="x", rotation=45)

    plt.tight_layout()
    plt.savefig(os.path.join(pasta_previews, "datacube_iv_nan_stats.png"),
                dpi=100, bbox_inches="tight")
    plt.close()

    # ------------------------------------------------------------------
    # Grafico 2: Media temporal por indice
    # ------------------------------------------------------------------
    n_feat = min(F, len(feat_labels))
    cols_g = min(n_feat, 5)
    rows_g = (n_feat + cols_g - 1) // cols_g
    fig, axes = plt.subplots(rows_g, cols_g, figsize=(cols_g * 3, rows_g * 3))
    axes_flat = np.array(axes).flatten() if n_feat > 1 else [axes]

    for i in range(n_feat):
        mapa = np.nanmean(dc_iv[:, :, :, i], axis=0)
        im   = axes_flat[i].imshow(mapa, cmap="RdYlGn", vmin=0, vmax=1)
        axes_flat[i].set_title(feat_labels[i], fontsize=8)
        axes_flat[i].axis("off")
        plt.colorbar(im, ax=axes_flat[i], fraction=0.046, pad=0.04)
    for j in range(n_feat, len(axes_flat)):
        axes_flat[j].axis("off")

    fig.suptitle(f"Datacube IV — Media temporal ({T} periodos) [0-1 norm]", fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(pasta_previews, "datacube_iv_mapas_medios.png"),
                dpi=100, bbox_inches="tight")
    plt.close()

    # ------------------------------------------------------------------
    # Grafico 3: Desvio padrao temporal por indice
    # Mostra quais areas tem maior variabilidade ao longo da serie
    # (complemento da media — identifica zonas instáveis vs. estáveis)
    # ------------------------------------------------------------------
    fig, axes = plt.subplots(rows_g, cols_g, figsize=(cols_g * 3, rows_g * 3))
    axes_flat = np.array(axes).flatten() if n_feat > 1 else [axes]

    for i in range(n_feat):
        mapa_std = np.nanstd(dc_iv[:, :, :, i], axis=0)
        im       = axes_flat[i].imshow(mapa_std, cmap="YlOrRd", vmin=0, vmax=0.4)
        axes_flat[i].set_title(feat_labels[i], fontsize=8)
        axes_flat[i].axis("off")
        plt.colorbar(im, ax=axes_flat[i], fraction=0.046, pad=0.04)
    for j in range(n_feat, len(axes_flat)):
        axes_flat[j].axis("off")

    fig.suptitle(f"Datacube IV — Desvio Padrao temporal ({T} periodos) [0-1 norm]", fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(pasta_previews, "datacube_iv_mapas_std.png"),
                dpi=100, bbox_inches="tight")
    plt.close()
    print(f"  [OK] IV: mapas de media e desvio padrao temporal gerados")

    # ------------------------------------------------------------------
    # Grafico 4: Serie temporal media da area por indice
    # ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(15, 5))
    colors  = plt.cm.tab10(np.linspace(0, 1, n_feat))
    for i in range(n_feat):
        serie = np.nanmean(dc_iv[:, :, :, i], axis=(1, 2))
        ax.plot(range(T), serie, label=feat_labels[i], color=colors[i], linewidth=1.2)

    ax.set_xticks(range(0, T, xtick_step))
    ax.set_xticklabels(time_labels[::xtick_step], rotation=45, ha='right', fontsize=7)
    ax.set_ylabel("Valor normalizado [0-1]")
    ax.set_title(f"Serie temporal — media da area ({nome_cliente})")
    ax.legend(loc='upper left', fontsize=7, ncol=3)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(pasta_previews, "datacube_iv_serie_temporal.png"),
                dpi=100, bbox_inches="tight")
    plt.close()

    # ------------------------------------------------------------------
    # Grafico 5: Medias climatologicas mensais por indice
    # Para cada indice: uma figura com 12 subplots (Jan-Dez) mostrando
    # a media espacial acumulada de todos os anos disponiveis para
    # aquele mes. Titulo de cada subplot inclui o valor medio da area.
    # ------------------------------------------------------------------
    MESES_PT = ["Janeiro","Fevereiro","Marco","Abril","Maio","Junho",
                "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

    # Mapear cada posicao temporal ao seu mes calendario (1-12)
    meses_t = [int(lbl[4:6]) for lbl in time_labels]   # ex: "20220601" -> 6

    print(f"  -> Gerando medias climatologicas mensais por indice...")

    for i in range(n_feat):
        nome_idx = feat_labels[i]
        fig, axes = plt.subplots(3, 4, figsize=(4 * 3.2, 3 * 2.8))
        axes_flat = axes.flatten()

        for m in range(1, 13):   # m = 1..12
            ax = axes_flat[m - 1]

            # Indices temporais que correspondem ao mes m
            t_indices = [t for t, mes in enumerate(meses_t) if mes == m]

            if not t_indices:
                ax.set_facecolor("#eeeeee")
                ax.text(0.5, 0.5, "sem dados", ha='center', va='center',
                        fontsize=7, transform=ax.transAxes, color='gray')
                ax.set_title(MESES_PT[m - 1], fontsize=8)
                ax.axis("off")
                continue

            # Media espacial do mes: media de todas as imagens desse mes
            stack = np.stack([dc_iv[t, :, :, i] for t in t_indices], axis=0)
            mapa_mes = np.nanmean(stack, axis=0)     # (H, W)

            # Media escalar da area para este mes (excluindo NaN)
            media_area = float(np.nanmean(mapa_mes))

            n_anos = len(t_indices)
            titulo = f"{MESES_PT[m-1]}\nmédia={media_area:.3f}  (n={n_anos})"

            im = ax.imshow(mapa_mes, cmap="RdYlGn", vmin=0, vmax=1,
                           interpolation='nearest', aspect='auto')
            ax.set_title(titulo, fontsize=7, pad=2)
            ax.axis("off")
            plt.colorbar(im, ax=ax, fraction=0.046, pad=0.03)

        fig.suptitle(f"{nome_idx} — Media climatologica mensal [0-1 norm]",
                     fontsize=11, y=1.01)
        plt.tight_layout(pad=0.5, h_pad=1.2, w_pad=0.4)
        saida = os.path.join(pasta_previews, f"datacube_iv_climatologia_{nome_idx}.png")
        plt.savefig(saida, dpi=120, bbox_inches="tight")
        plt.close()
        print(f"     [OK] {nome_idx}")

    print(f"  [OK] Mapas climatologicos mensais gerados para {n_feat} indices")
    print(f"  [OK] % NaN por indice: " +
          " | ".join(f"{feat_labels[i]}={nan_pct_feat[i]:.1f}%" for i in range(n_feat)))

# =====================================================================
# 2. DATACUBE ESTÁTICO (TOPOGRAFIA)
# =====================================================================
path_st      = os.path.join(pasta_saida_dc, f"Estatico_{nome_cliente}_norm01.npy")
path_st_feat = path_st.replace('.npy', '_feature_names.txt')

if os.path.exists(path_st):
    dc_st  = np.load(path_st)
    n_topo = dc_st.shape[0]
    nomes  = (open(path_st_feat).read().splitlines()
              if os.path.exists(path_st_feat) else variaveis_topo[:n_topo])

    print(f"\n  Datacube Estatico:  shape={dc_st.shape}")

    cols_t = min(n_topo, 5)
    rows_t = (n_topo + cols_t - 1) // cols_t
    fig, axes = plt.subplots(rows_t, cols_t, figsize=(cols_t * 3, rows_t * 3))
    axes_flat = np.array(axes).flatten() if n_topo > 1 else [axes]

    for i in range(n_topo):
        im = axes_flat[i].imshow(dc_st[i], cmap="terrain", vmin=0, vmax=1)
        axes_flat[i].set_title(nomes[i] if i < len(nomes) else f"Topo{i}", fontsize=8)
        axes_flat[i].axis("off")
        plt.colorbar(im, ax=axes_flat[i], fraction=0.046, pad=0.04)
    for j in range(n_topo, len(axes_flat)):
        axes_flat[j].axis("off")

    fig.suptitle("Datacube Estatico — Variaveis Topograficas (norm 0-1)", fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(pasta_previews, "datacube_estatico_mapas.png"),
                dpi=100, bbox_inches="tight")
    plt.close()
    print(f"  [OK] Estatico: mapas topograficos gerados")
else:
    print(f"  [AVISO] Datacube Estatico nao encontrado: {path_st}")

print(f"\n[OK] Auditoria 3 concluida. Previews em: {pasta_previews}/")
print(f"     Ficheiros gerados:")
print(f"       datacube_iv_nan_stats.png")
print(f"       datacube_iv_mapas_medios.png")
print(f"       datacube_iv_mapas_std.png")
print(f"       datacube_iv_serie_temporal.png")
print(f"       datacube_iv_mensal_<INDICE>.png  (um por indice)")
print(f"       datacube_estatico_mapas.png")
