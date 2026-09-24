/* Punto de entrada del dashboard.
 *
 * El panel SEO vive en app.core.js y la extensión de Instagram en instagram.js.
 * Se cargan en ese orden para que la pestaña de Instagram se monte sobre un
 * shell ya inicializado. El split mantiene ambos flujos aislados: un error al
 * importar la extensión no deja el panel SEO sin arrancar.
 */
(async () => {
  await import("/dashboard/app.core.js");
  try {
    await import("/dashboard/instagram.js");
  } catch (error) {
    console.error("No se pudo cargar la extensión de Instagram", error);
  }
  try {
    await import("/dashboard/post-bot.js");
  } catch (error) {
    console.error("No se pudo cargar la extensión de la cola de posts", error);
  }
})();
