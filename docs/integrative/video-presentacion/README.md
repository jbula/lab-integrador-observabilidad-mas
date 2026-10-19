# Video de presentación

Destino del video de la demostración en vivo del laboratorio integrador.

## Límites de tamaño en GitHub

GitHub impone límites estrictos al tamaño de archivo que conviene conocer antes
de subir la grabación:

| Tamaño del archivo | Comportamiento |
|---|---|
| Hasta 50 MB | Se sube sin advertencias |
| Entre 50 MB y 100 MB | Se sube, pero GitHub emite una advertencia |
| Más de 100 MB | **Rechazado.** El push falla por completo |

El límite de 100 MB es un rechazo duro del lado del servidor, no una
recomendación. Una grabación de pantalla de diez a quince minutos a 1080p
supera ese límite con facilidad, de modo que conviene decidir el método antes
de grabar.

## Opciones

**Comprimir por debajo de 100 MB.** Suficiente para una demostración de
terminal y navegador, donde la imagen es mayormente estática y comprime bien:

```bash
ffmpeg -i grabacion-original.mov \
  -vcodec libx264 -crf 30 -preset slow \
  -vf "scale=1280:-2" \
  -acodec aac -b:a 96k \
  demo-laboratorio-integrador.mp4
```

Un valor de `crf` más alto reduce el tamaño a costa de calidad; entre 28 y 32
suele conservar el texto de la terminal legible. Verificar el resultado antes
de subirlo:

```bash
ls -lh demo-laboratorio-integrador.mp4
```

**Git LFS**, si el archivo no baja de 100 MB. Requiere configuración previa en
el repositorio y consume la cuota de LFS de la cuenta:

```bash
git lfs install
git lfs track "docs/integrative/video-presentacion/*.mp4"
git add .gitattributes
```

**Enlace externo.** Alojar el video en YouTube como no listado, o en Drive, y
dejar aquí únicamente la URL. Es la opción que evita por completo el problema
de tamaño y la que suele preferirse para entregas académicas.

## Contenido

El guion de la demostración, con el paso a paso de los comandos que se ejecutan
en vivo, se encuentra en `../video-script.md`.
