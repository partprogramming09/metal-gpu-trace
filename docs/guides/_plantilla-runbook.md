# [Verbo + objeto]: por ejemplo "Desplegar a producción"

**Lector:** personas — [quién la ejecuta y qué sabe]
**Última verificación:** AAAA-MM-DD
**Cuándo usar esta guía:** situación concreta
**Quién puede ejecutarla:**
**Lleva:** [tiempo aproximado] · **Pasos:** N

## Requisitos previos
- [ ]

## Pasos
Una acción por paso. Cada paso dice qué debe verse si salió bien y, si suele fallar, el error con su síntoma **en ese mismo paso**.

### Paso 1 de N: [acción]
- [ ] Hecho
```bash
comando
```
**Deberías ver:** lo que debe salir.
**Si falla:** síntoma exacto → causa → qué hacer.

### Paso 2 de N: [acción]
- [ ] Hecho

## Cómo comprobar que salió bien
-

## Si algo falla y no es de un paso
| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| | | |

## Cómo deshacerlo (rollback)
1.

## Variante «ejercicio» (construir algo nuevo, por capas)
Solo si la guía enseña a construir algo en vez de repetir un procedimiento. Cambia tres cosas:
- Los pasos van agrupados por capa (por ejemplo: datos, lógica, entrada), con un título por capa.
- A mitad se prueba lo hecho hasta ese punto («deberías ver…») antes de seguir con la capa siguiente.
- Al final, un resultado que se puede ejecutar y los errores más probables de cada capa.

## Relacionado
- ADR o documentos enlazados
