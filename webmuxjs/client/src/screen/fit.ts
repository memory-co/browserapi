/**
 * 尺寸和"有效缩放" —— **纯算术,单独测。**
 *
 * 有效缩放 = 物理像素 / 帧原始像素。**1.00x 才是像素级对齐。**
 * 这一栏正是用来判断该不该调 `dsf` 的,算错了整条调优就没依据了。
 *
 * 那个坑:**帧的真实尺寸只有解码之后才知道。** CDP 的 metadata 报的是
 * CSS 尺寸,`dsf=2` 时它说 1024×768,而图其实是 2048×1536 ——
 * 拿它算会差一倍。所以只信 `img.naturalWidth`。
 */

export function effectiveZoom(
  cssWidth: number, devicePixelRatio: number, frameWidth: number,
): number {
  if (!frameWidth) return 0;
  return (cssWidth * devicePixelRatio) / frameWidth;
}

/** 差 2% 以内算对齐 —— 再严就会因为小数取整一直报红。 */
export function aligned(zoom: number): boolean {
  return Math.abs(zoom - 1) < 0.02;
}

/** DOM 重放那棵树按容器宽度缩放。 */
export function replayScale(containerWidth: number, frameWidth: number): number {
  if (!frameWidth || !containerWidth) return 1;
  return containerWidth / frameWidth;
}
