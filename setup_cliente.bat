@echo off
:: ============================================================
:: setup_cliente.bat
:: Cria a estrutura de pastas para um novo cliente no HD.
::
:: Uso: .\setup_cliente.bat LETRA_HD NOME_CLIENTE [NOME_FAZENDA]
::
:: Exemplos:
::   .\setup_cliente.bat D Nome_Cliente fazenda
::        -> cria D:\clientes\Nome_Cliente\inputs\fazenda\
::
::   .\setup_cliente.bat D Fazenda_Cafe
::        -> cria D:\clientes\Fazenda_Cafe\inputs\
:: ============================================================

if "%~2"=="" (
    echo Uso: .\setup_cliente.bat LETRA_HD NOME_CLIENTE [NOME_FAZENDA]
    echo Exemplo: .\setup_cliente.bat D Nome_Cliente fazenda
    exit /b 1
)

set HD=%~1
set CLIENTE=%~2
set FAZENDA=%~3
set BASE=%HD%:\clientes\%CLIENTE%

echo Criando estrutura para: %CLIENTE%
echo Base: %BASE%

if "%FAZENDA%"=="" (
    mkdir "%BASE%\inputs"            2>nul
) else (
    mkdir "%BASE%\inputs\%FAZENDA%"  2>nul
)

mkdir "%BASE%\TOPOGRAFIA"        2>nul
mkdir "%BASE%\HANTS"             2>nul
mkdir "%BASE%\HANTS_REPROJETADO" 2>nul
mkdir "%BASE%\DATACUBE"          2>nul
mkdir "%BASE%\PREVIEWS"          2>nul

echo.
echo [OK] Estrutura criada com sucesso!
echo.
echo Proximos passos:
if "%FAZENDA%"=="" (
    echo   1. Copiar o shapefile para: %BASE%\inputs\
    echo   2. docker run ... -e CLIENTE_NOME=%CLIENTE% -e SHP_FILENAME=nome.shp ...
) else (
    echo   1. Copiar o shapefile para: %BASE%\inputs\%FAZENDA%\
    echo   2. docker run ... -e CLIENTE_NOME=%CLIENTE% -e SHP_FILENAME=%FAZENDA%/%FAZENDA%.shp ...
)
