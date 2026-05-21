import os

# =====================================================================
# ETAPA 1: DEFINICAO DE CAMINHOS DENTRO DO DOCKER
# =====================================================================
hants_dir  = '/app/hants'
davgis_dir = os.path.join(hants_dir, 'davgis')

os.makedirs(davgis_dir, exist_ok=True)

print("Iniciando a aplicacao de patches Python 3 ao repositorio HANTS...")

# =====================================================================
# ETAPA 2: PATCH PARA O 'davgis/functions.py'
# Substitui todas as dependencias osgeo (gdal/ogr/osr) por rasterio + pyproj
# =====================================================================
functions_py_content = """# -*- coding: utf-8 -*-
# davgis/functions.py  -- PATCH: osgeo substituido por rasterio + pyproj
import os
import numpy as np
import netCDF4
import math
import warnings
import rasterio
from rasterio.windows import Window
from rasterio.transform import from_origin
from pyproj import CRS


def Raster_to_Array(input_tiff, ll_corner, x_ncells, y_ncells, values_type='float32'):
    give_warning = False
    try:
        with rasterio.open(input_tiff) as inp_ds:
            t = inp_ds.transform
            top_left_x_raster    = t.c
            cellsize_x_raster    = t.a
            top_left_y_raster    = t.f
            cellsize_y_raster    = t.e          # negativo
            NoData_value_raster  = inp_ds.nodata
            x_total_pixels_raster = inp_ds.width
            y_total_pixels_raster = inp_ds.height

            xmin_array = ll_corner[0]
            ymin_array = ll_corner[1]

            x_offset_read = int(round((xmin_array - top_left_x_raster) / cellsize_x_raster))
            y_offset_read = int(round((top_left_y_raster - (ymin_array + y_ncells * abs(cellsize_y_raster))) / abs(cellsize_y_raster)))

            final_array = np.full((y_ncells, x_ncells), np.nan, dtype=np.dtype(values_type))

            src_x_start = max(0, x_offset_read)
            src_y_start = max(0, y_offset_read)
            dst_x_start = max(0, -x_offset_read)
            dst_y_start = max(0, -y_offset_read)

            win_x_size = min(x_ncells - dst_x_start, x_total_pixels_raster - src_x_start)
            win_y_size = min(y_ncells - dst_y_start, y_total_pixels_raster - src_y_start)
            win_x_size = max(0, win_x_size)
            win_y_size = max(0, win_y_size)

            if win_x_size > 0 and win_y_size > 0:
                window = Window(src_x_start, src_y_start, win_x_size, win_y_size)
                array_read = inp_ds.read(1, window=window).astype(np.dtype(values_type))
                if NoData_value_raster is not None:
                    try:
                        if not np.isnan(float(NoData_value_raster)):
                            array_read[np.isclose(array_read, NoData_value_raster)] = np.nan
                    except (TypeError, ValueError):
                        pass
                final_array[dst_y_start:dst_y_start+win_y_size, dst_x_start:dst_x_start+win_x_size] = array_read
                if dst_x_start > 0 or dst_y_start > 0 or \
                   (dst_x_start + win_x_size) < x_ncells or \
                   (dst_y_start + win_y_size) < y_ncells:
                    give_warning = True
            else:
                give_warning = True

    except Exception as e:
        warnings.warn(f'[davgis.Raster_to_Array] ERRO ao abrir {input_tiff}: {e}')
        return np.full((y_ncells, x_ncells), np.nan, dtype=np.dtype(values_type))

    if give_warning:
        warnings.warn('[davgis.Raster_to_Array] Area solicitada parcial ou totalmente fora do raster.')
    return final_array


def Spatial_Reference(epsg, return_string=True):
    crs = CRS.from_epsg(int(epsg))
    if return_string:
        return crs.to_wkt()
    return crs


def List_Datasets(path, ext):
    datsets_ls = []
    ext_with_dot = ext if ext.startswith('.') else '.' + ext.lower()
    for f_name in os.listdir(path):
        if os.path.splitext(f_name)[1].lower() == ext_with_dot:
            datsets_ls.append(f_name)
    return datsets_ls


def NetCDF_to_Raster(input_nc, output_tiff, ras_variable,
                     x_variable='longitude', y_variable='latitude',
                     crs={'variable': 'crs', 'wkt': 'spatial_ref'}, time=None):
    inp_nc_ds      = netCDF4.Dataset(input_nc, 'r')
    inp_values_var = inp_nc_ds.variables[ras_variable]

    # --- Selecionar fatia 2D ---
    inp_array_2d_slice = None
    if not time:
        if len(inp_values_var.shape) == 2:
            inp_array_2d_slice = np.array(inp_values_var[:])
        elif len(inp_values_var.shape) == 3 and inp_values_var.shape[0] == 1:
            inp_array_2d_slice = np.array(inp_values_var[0, :, :])
    else:
        time_dim_name_in_var = time['variable']
        time_value_to_find   = time['value']
        time_data_array      = inp_nc_ds.variables[time_dim_name_in_var][:]
        if np.issubdtype(type(time_value_to_find), np.number) and np.issubdtype(time_data_array.dtype, np.number):
            # Comparacao inteira exacta: np.isclose com rtol=1e-5 falha para datas YYYYMMDD
            # porque a tolerancia relativa (~202) e maior que a diferenca entre meses (~100),
            # fazendo com que Janeiro, Fevereiro e Marco colapssem no mesmo slice.
            time_index_matches = np.where(
                np.abs(time_data_array.astype(np.int64) - int(time_value_to_find)) < 1
            )[0]
        else:
            time_index_matches = np.where(time_data_array == time_value_to_find)[0]
        time_index = int(time_index_matches[0])
        slicer = [slice(None)] * len(inp_values_var.shape)
        time_axis_idx = list(inp_values_var.dimensions).index(time_dim_name_in_var)
        slicer[time_axis_idx] = time_index
        inp_array_2d_slice = np.array(inp_values_var[tuple(slicer)])

    # --- Determinar nodata ---
    NoData_value_to_set = -9999.0
    if hasattr(inp_values_var, '_FillValue'):
        fv = inp_values_var._FillValue
        if isinstance(fv, (np.ndarray, list)):
            NoData_value_to_set = float(fv.item(0)) if len(fv) > 0 else -9999.0
        else:
            NoData_value_to_set = float(fv)

    # --- CRS ---
    if isinstance(crs, str):
        srs_wkt_final = crs
    else:
        crs_var_obj   = inp_nc_ds.variables[crs['variable']]
        srs_wkt_final = str(getattr(crs_var_obj, crs['wkt']))

    # --- Coordenadas e transform ---
    inp_x_coords = np.array(inp_nc_ds.variables[x_variable][:])
    inp_y_coords = np.array(inp_nc_ds.variables[y_variable][:])

    cellsize_x_calc = float(np.abs(np.mean(np.diff(inp_x_coords)))) if len(inp_x_coords) > 1 else 1.0
    cellsize_y_calc = float(np.abs(np.mean(np.diff(inp_y_coords)))) if len(inp_y_coords) > 1 else 1.0

    out_gt_top_left_x = float(np.min(inp_x_coords)) - (cellsize_x_calc / 2.0)
    out_gt_top_left_y = float(np.max(inp_y_coords)) + (cellsize_y_calc / 2.0)

    final_array_to_write = inp_array_2d_slice.astype(np.float32)
    if len(inp_y_coords) > 1 and inp_y_coords[0] < inp_y_coords[-1]:
        final_array_to_write = np.flipud(final_array_to_write)

    y_ncells_arr, x_ncells_arr = final_array_to_write.shape
    transform = from_origin(out_gt_top_left_x, out_gt_top_left_y, cellsize_x_calc, cellsize_y_calc)

    inp_nc_ds.close()

    if os.path.exists(output_tiff):
        os.remove(output_tiff)

    with rasterio.open(
        output_tiff, 'w',
        driver='GTiff',
        height=y_ncells_arr,
        width=x_ncells_arr,
        count=1,
        dtype='float32',
        crs=srs_wkt_final,
        transform=transform,
        nodata=NoData_value_to_set,
        compress='lzw',
    ) as out_ds:
        out_ds.write(final_array_to_write, 1)

    return output_tiff
"""

with open(os.path.join(davgis_dir, 'functions.py'), 'w', encoding='utf-8') as f:
    f.write(functions_py_content)
print("  [OK] Arquivo 'davgis/functions.py' atualizado!")


# =====================================================================
# ETAPA 3: PATCH PARA O 'hants_main_runner.py'
# =====================================================================
hants_main_runner_content = """# -*- coding: utf-8 -*-
# hants_main_runner.py  -- PATCH: osgeo substituido por pyproj
import netCDF4
import pandas as pd
import numpy as np
import math
import glob
from davgis.functions import (Spatial_Reference, Raster_to_Array, NetCDF_to_Raster)
import os
import warnings
from pyproj import CRS as _ProjCRS

def run_HANTS(rasters_path_inp, vi_name_for_files,
              start_date, end_date, latlim, lonlim, cellsize, nc_path,
              nb, nf, HiLo, low, high, fet, dod, delta,
              epsg=4326, fill_val=-9999.0,
              rasters_path_out=None, export_hants_only=False,
              output_filename_template="{0}_HANTS_{1}.tif",
              frequencia='mensal',
              excluir=None):
    # excluir: dict ou set de basenames de ficheiros a ignorar durante create_netcdf.
    #          Tipicamente gerado pela funcao detectar_imagens_problematicas() em 2-HANTS.py.

    create_netcdf(
        rasters_path=rasters_path_inp,
        vi_name=vi_name_for_files,
        start_date_str=start_date,
        end_date_str=end_date,
        latlim=latlim,
        lonlim=lonlim,
        cellsize=cellsize,
        nc_path=nc_path,
        epsg=epsg,
        fill_val=fill_val,
        frequencia=frequencia,
        low=float(low),
        high=float(high),
        excluir=excluir,
    )

    HANTS_netcdf(nc_path, nb, nf, HiLo, low, high, fet, dod, delta, fill_val)

    if rasters_path_out:
        export_tiffs(rasters_path_out, nc_path, vi_name_for_files, output_filename_template, export_hants_only)
    return nc_path

def create_netcdf(rasters_path, vi_name, start_date_str, end_date_str,
                  latlim, lonlim, cellsize, nc_path,
                  epsg=4326, fill_val=-9999.0, frequencia='mensal',
                  low=None, high=None, excluir=None):

    cs = abs(float(cellsize))
    lat_coords_center = np.arange(latlim[0] + cs/2.0, latlim[1], cs)
    lon_coords_center = np.arange(lonlim[0] + cs/2.0, lonlim[1], cs)
    lat_coords_for_nc = np.sort(lat_coords_center)[::-1]
    lon_coords_for_nc = np.sort(lon_coords_center)
    lat_n = len(lat_coords_for_nc)
    lon_n = len(lon_coords_for_nc)

    spa_ref_wkt    = _ProjCRS.from_epsg(int(epsg)).to_wkt()
    grid_ll_corner = [lonlim[0], latlim[0]]
    excluir_set    = set(excluir.keys()) if isinstance(excluir, dict) else (set(excluir) if excluir else set())

    # Frequencia mensal (MS = Month Start) ou semanal (W-MON = semanas a comecar na 2a feira)
    freq_pandas = 'W-MON' if frequencia == 'semanal' else 'MS'
    dates_dt_monthly   = pd.date_range(start_date_str, end_date_str, freq=freq_pandas)
    time_values_for_nc = [int(d.strftime('%Y%m%d')) for d in dates_dt_monthly]
    empty_vec = np.full((lat_n, lon_n), float(fill_val), dtype=np.float32)

    with netCDF4.Dataset(nc_path, 'w', format="NETCDF4") as nc_file:
        nc_file.createDimension('latitude',  lat_n)
        nc_file.createDimension('longitude', lon_n)
        nc_file.createDimension('time', len(time_values_for_nc))

        crs_var = nc_file.createVariable('crs', 'i4')
        crs_var.spatial_ref = spa_ref_wkt

        lat_var = nc_file.createVariable('latitude',  'f8', ('latitude',))
        lat_var[:] = lat_coords_for_nc

        lon_var = nc_file.createVariable('longitude', 'f8', ('longitude',))
        lon_var[:] = lon_coords_for_nc

        time_var = nc_file.createVariable('time', 'i4', ('time',))
        time_var[:] = time_values_for_nc

        outliers_var  = nc_file.createVariable('outliers',        'i1', ('latitude','longitude','time'), fill_value=np.int8(-1))
        original_var  = nc_file.createVariable('original_values', 'f4', ('latitude','longitude','time'), fill_value=float(fill_val))
        hants_var     = nc_file.createVariable('hants_values',    'f4', ('latitude','longitude','time'), fill_value=float(fill_val))
        combined_var  = nc_file.createVariable('combined_values', 'f4', ('latitude','longitude','time'), fill_value=float(fill_val))

        for tt, date_obj in enumerate(dates_dt_monthly):
            year_str  = date_obj.strftime('%Y')
            month_str = date_obj.strftime('%m')
            day_str   = date_obj.strftime('%d')

            # Suporte a frequencia mensal e semanal:
            #   Mensal  -> NDVI_2022-01.tif
            #   Semanal -> NDVI_2022-10-03_a_10-09.tif  (2a feira da semana)
            if frequencia == 'semanal':
                pattern = os.path.join(rasters_path, f"{vi_name}_{year_str}-{month_str}-{day_str}_a_*.tif")
                matched = glob.glob(pattern)
                expected_raster_path = matched[0] if matched else None
            else:
                expected_raster_path = os.path.join(rasters_path, f"{vi_name}_{year_str}-{month_str}.tif")

            # Ignorar ficheiros detectados como problematicos pela deteccao automatica
            if expected_raster_path and os.path.basename(expected_raster_path) in excluir_set:
                original_var[:, :, tt] = empty_vec
                continue

            if expected_raster_path and os.path.exists(expected_raster_path):
                try:
                    array = Raster_to_Array(expected_raster_path, grid_ll_corner, lon_n, lat_n, values_type='float32')
                    if hasattr(array, 'shape') and array.shape == (lat_n, lon_n):
                        # Capping: valores fora do intervalo valido sao tratados como nodata
                        # antes de entrar no HANTS, evitando que outliers extremos (sombras
                        # de nuvem nao detectadas, artefactos de borda) contaminem a reconstrucao.
                        valid_mask = np.isfinite(array) & ~np.isclose(array, float(fill_val))
                        if low is not None:
                            array[valid_mask & (array < float(low))] = float(fill_val)
                        if high is not None:
                            array[valid_mask & (array > float(high))] = float(fill_val)
                        original_var[:, :, tt] = array
                    else:
                        original_var[:, :, tt] = empty_vec
                except Exception as e:
                    original_var[:, :, tt] = empty_vec
            else:
                original_var[:, :, tt] = empty_vec

    return nc_path

def HANTS_netcdf(nc_path, nb, nf, HiLo, low, high, fet, dod, delta, fill_val=-9999.0):
    with netCDF4.Dataset(nc_path, 'r+') as nc_file:
        time_data            = nc_file.variables['time'][:]
        original_values_data = nc_file.variables['original_values'][:]
        [rows, cols, ztime]  = original_values_data.shape

        values_hants_result   = np.full((rows, cols, ztime), float(fill_val), dtype=np.float32)
        outliers_hants_result = np.full((rows, cols, ztime), -1, dtype=np.int8)

        ni   = len(time_data)
        ts_np = np.arange(ni, dtype=np.float64)

        for r_idx in range(rows):
            for c_idx in range(cols):
                pixel_timeseries = original_values_data[r_idx, c_idx, :].astype(np.float64)
                pixel_timeseries[np.isnan(pixel_timeseries)] = float(fill_val)

                if not np.all(np.isclose(pixel_timeseries, float(fill_val))):
                    try:
                        yr, outliers_pixel = HANTS(ni, int(nb), int(nf), pixel_timeseries, ts_np,
                                                   str(HiLo), float(low), float(high),
                                                   float(fet), int(dod), float(delta), float(fill_val))
                        values_hants_result[r_idx, c_idx, :]   = yr.flatten()
                        outliers_hants_result[r_idx, c_idx, :] = outliers_pixel.flatten().astype(np.int8)
                    except:
                        pass

        nc_file.variables['hants_values'][:]  = values_hants_result
        nc_file.variables['outliers'][:]      = outliers_hants_result

        original_is_fill     = np.isclose(original_values_data, float(fill_val))
        condition_use_hants  = (outliers_hants_result == 1) | original_is_fill
        nc_file.variables['combined_values'][:] = np.where(condition_use_hants, values_hants_result, original_values_data)

def HANTS(ni, nb, nf, y_in, ts_in, HiLo_str, low_val, high_val, fet_val, dod_val, delta_val, fill_val_num):
    y   = y_in.copy().astype(np.float64)
    ts  = ts_in.astype(np.float64)
    mat = np.zeros((min(2 * nf + 1, ni), ni), dtype=np.float64)
    outliers = np.zeros((ni,), dtype=np.int8)

    sHiLo = 0
    if HiLo_str.lower() == 'hi': sHiLo = -1
    elif HiLo_str.lower() == 'lo': sHiLo = 1

    nr = min(2 * nf + 1, ni)
    noutmax = max(0, ni - nr - dod_val)

    mat[0, :] = 1.0
    ang = (2.0 * math.pi / nb) * np.arange(nb, dtype=np.float64)
    cs  = np.cos(ang)
    sn  = np.sin(ang)

    for i_freq_idx in range(1, nf + 1):
        for j_time_idx in range(ni):
            angle_index = int(round((i_freq_idx * ts[j_time_idx]))) % nb
            mat[2 * i_freq_idx - 1, j_time_idx] = cs[angle_index]
            mat[2 * i_freq_idx,     j_time_idx] = sn[angle_index]

    p = np.ones_like(y, dtype=np.float64)
    initial_outliers_bool = (y < low_val) | (y > high_val)
    p[initial_outliers_bool] = 0.0
    outliers[initial_outliers_bool] = 1
    nout = np.sum(p == 0.0)

    if nout > noutmax:
        if np.all(p == 0.0) and np.all(np.isclose(y[initial_outliers_bool], fill_val_num)):
            return [y.copy().reshape(-1, 1), outliers.reshape(1, -1)]
        else:
            raise ValueError(f"HANTS pixel stop: Initial outliers ({nout}) > noutmax ({noutmax})")

    ready = False
    nloop = 0
    yr_candidate = np.zeros_like(y)

    while not ready and nloop < ni:
        nloop += 1
        za = np.dot(mat, p * y)
        A  = np.dot(mat * p, mat.T)
        A  = A + np.identity(nr) * delta_val
        A[0, 0] = A[0, 0] - delta_val
        try:
            zr = np.linalg.solve(A, za)
        except np.linalg.LinAlgError:
            outliers.fill(1)
            return [y.copy().reshape(-1, 1), outliers.reshape(1, -1)]

        yr_candidate     = np.dot(mat.T, zr)
        diff_vec         = sHiLo * (yr_candidate - y)
        errors_for_valid = p * diff_vec

        if np.sum(p) < 1e-6 or nout == noutmax:
            ready = True
            continue

        valid_indices = np.where(p > 0.5)[0]
        if len(valid_indices) == 0:
            ready = True
            continue

        errors_in_valid = errors_for_valid[valid_indices]
        max_err = np.max(errors_in_valid) if len(errors_in_valid) > 0 else -1.0

        if max_err <= fet_val:
            ready = True
        else:
            idx_max = valid_indices[np.argmax(errors_in_valid)]
            p[idx_max] = 0.0
            outliers[idx_max] = 1
            nout += 1

    return [yr_candidate.copy().reshape(-1, 1), outliers.reshape(1, -1)]

def export_tiffs(rasters_path_out, nc_path, vi_name, output_filename_template, export_hants_only=False):
    os.makedirs(rasters_path_out, exist_ok=True)

    with netCDF4.Dataset(nc_path, 'r') as nc_file:
        time_values_from_nc = nc_file.variables['time'][:]

    variable_selected = 'hants_values' if export_hants_only else 'combined_values'

    for t_idx, time_val_in_nc in enumerate(time_values_from_nc):
        output_filename_base = output_filename_template.format(vi_name, str(int(time_val_in_nc)))
        output_full_path     = os.path.join(rasters_path_out, output_filename_base)
        try:
            NetCDF_to_Raster(input_nc=nc_path, output_tiff=output_full_path,
                             ras_variable=variable_selected,
                             x_variable='longitude', y_variable='latitude',
                             crs={'variable': 'crs', 'wkt': 'spatial_ref'},
                             time={'variable': 'time', 'value': time_val_in_nc})
        except Exception as e:
            print(f"Erro ao exportar {output_filename_base}: {e}")

    return rasters_path_out
"""

with open(os.path.join(hants_dir, 'hants_main_runner.py'), 'w', encoding='utf-8') as f:
    f.write(hants_main_runner_content)
print("  [OK] Arquivo 'hants_main_runner.py' atualizado!")


# =====================================================================
# ETAPA 4: PATCH PARA O 'davgis/__init__.py'
# =====================================================================
davgis_init_content = """# -*- coding: utf-8 -*-
# davgis/__init__.py (PATCH PARA PYTHON 3)
try:
    from .functions import *
except Exception as e:
    print(f"Erro de importacao em davgis/__init__.py: {e}")

__all__ = ['Buffer', 'Feature_to_Raster', 'List_Fields', 'Raster_to_Array',
           'Resample', 'Array_to_Raster', 'Clip', 'Raster_to_Points',
           'Add_Field', 'Spatial_Reference', 'List_Datasets',
           'NetCDF_to_Raster', 'Apply_Filter', 'Extract_Band', 'Interpolation']
__version__ = '0.1'
"""

with open(os.path.join(davgis_dir, '__init__.py'), 'w', encoding='utf-8') as f:
    f.write(davgis_init_content)
print("  [OK] Arquivo 'davgis/__init__.py' atualizado!")


print("\n[OK] Todos os patches foram aplicados! HANTS pronto para Python 3 e Docker.")
