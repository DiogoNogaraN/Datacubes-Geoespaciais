@echo off
:: ============================================================
:: processar_areas.bat
:: Processa multiplas areas de um mesmo cliente em sequencia.
:: Le as configuracoes de areas_lote.json e lanca um container
:: Docker por area, com log individual.
::
:: Uso: processar_areas.bat [areas_lote.json]
:: Padrao: areas_lote.json no diretorio atual
:: ============================================================
setlocal EnableDelayedExpansion

set LOTE_FILE=%~1
if "%LOTE_FILE%"=="" set LOTE_FILE=areas_lote.json

if not exist "%LOTE_FILE%" (
    echo ERRO: Ficheiro %LOTE_FILE% nao encontrado.
    echo Crie o ficheiro com a lista de areas. Ver exemplo em areas_lote.json.
    exit /b 1
)

:: Extrair campos do JSON com python (disponivel em todos os sistemas com Python 3)
for /f "delims=" %%i in ('python3 -c "import json,sys; d=json.load(open(\'%LOTE_FILE%\')); c=d[\'cliente\']; [print(k+\'=\'+str(v)) for k,v in c.items()]"') do (
    set %%i
)

echo ============================================================
echo  Processamento em Lote
echo  Cliente : %nome%
echo  HD      : %hd_letra%:\SEU_HD
echo  Periodo : %data_inicio% a %data_fim%
echo  SRC     : %src_projeto%
echo ============================================================
echo.

:: Criar pasta de logs
set LOG_BASE=%hd_letra%:\clientes\%nome%\logs_pipeline
mkdir "%LOG_BASE%" 2>nul

:: Iterar sobre cada area
for /f "delims=" %%A in ('python3 -c "import json,sys; d=json.load(open(\'%LOTE_FILE%\')); [print(a[\'nome\']+\'|\'+a.get(\'shp_filename\',\'contorno_fazenda.shp\')+\'|\'+a.get(\'parar_apos\',\'\')) for a in d[\'areas\']]"') do (
    for /f "tokens=1,2,3 delims=|" %%a in ("%%A") do (
        set AREA=%%a
        set SHP=%%b
        set PARAR=%%c

        echo ----------------------------------------------------------
        echo  Iniciando area: !AREA!
        echo ----------------------------------------------------------

        set LOG_FILE=%LOG_BASE%\!AREA!.log
        set PARAR_OPT=
        if not "!PARAR!"=="" set PARAR_OPT=-e PARAR_APOS_MODULO=!PARAR!

        docker run --rm ^
          -v "%hd_letra%:\SEU_HD:/dados" ^
          -e CLIENTE_NOME=%nome% ^
          -e NOME_AREA=!AREA! ^
          -e SHP_FILENAME=!SHP! ^
          -e SRC_PROJETO=%src_projeto% ^
          -e FREQUENCIA=%frequencia% ^
          -e MESES_SAFRA=%meses_safra% ^
          -e DATA_INICIO=%data_inicio% ^
          -e DATA_FIM=%data_fim% ^
          -e COPERNICUS_USER=%copernicus_user% ^
          -e COPERNICUS_PASS=%copernicus_pass% ^
          !PARAR_OPT! ^
          sentinel2-pipeline 2>&1 | tee "!LOG_FILE!"

        if !ERRORLEVEL! neq 0 (
            echo [ERRO] Area !AREA! falhou. Ver log em !LOG_FILE!
        ) else (
            echo [OK] Area !AREA! concluida com sucesso.
        )
        echo.
    )
)

echo ============================================================
echo  Lote concluido. Logs em: %LOG_BASE%\
echo ============================================================
