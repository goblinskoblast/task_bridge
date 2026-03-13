@echo off
echo Rebuilding React WebApp...
echo.

cd webapp

echo [1/2] Installing dependencies...
call npm install

echo.
echo [2/2] Building for production...
call npm run build

echo.
echo Build completed successfully!
echo Output directory: webapp/dist/
echo.
pause
