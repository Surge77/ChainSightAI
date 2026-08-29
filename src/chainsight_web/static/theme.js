/* The masthead theme switch.

   Loaded from <head> without `defer` on purpose. The attribute this writes onto <html>
   decides the palette, so it has to be written before the first paint -- deferred, the
   browser paints the system theme and then repaints the chosen one, and a light-mode
   operator opening a page gets a flash of dark that looks like a fault in the page.

   Three states rather than two. A plain toggle has no way back to "follow the system", so
   the first click would permanently pin a preference the visitor never asked to override.
   The stored value is a preference, not a session: it is per-browser, never sent anywhere,
   and its absence means system. */
(() => {
  "use strict";

  const KEY = "chainsight-theme";
  const CYCLE = ["system", "light", "dark"];
  const root = document.documentElement;

  /* localStorage throws rather than returning null when a browser is set to block site
     data, and a theme is not worth an exception that stops the rest of the page's scripts
     from running. Blocked storage degrades to "the choice lasts as long as the page". */
  const stored = () => {
    try {
      return window.localStorage.getItem(KEY);
    } catch {
      return null;
    }
  };

  const remember = (mode) => {
    try {
      if (mode === "system") {
        window.localStorage.removeItem(KEY);
      } else {
        window.localStorage.setItem(KEY, mode);
      }
    } catch {
      /* nothing to do: the mode is already applied, it just will not outlive the tab */
    }
  };

  const apply = (mode) => {
    if (mode === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", mode);
    }
  };

  const saved = stored();
  let mode = CYCLE.includes(saved) ? saved : "system";
  apply(mode);

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("theme-toggle");
    if (button === null) {
      return;
    }

    const word = button.querySelector(".theme-label");
    const icons = button.querySelectorAll(".theme-icon");

    /* The word is written into its own span rather than onto the button, because writing
       `button.textContent` would replace the three marks along with it. */
    const label = () => {
      word.textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
      /* `toggleAttribute`, not `icon.hidden = ...`. `hidden` is an IDL attribute of
         HTMLElement and an <svg> is an SVGElement, so the assignment sets a property nobody
         reads and all three marks stay on screen -- which is exactly what it did. The
         attribute is real either way; `.theme-icon[hidden]` in the stylesheet is what acts
         on it, because the browser's own `[hidden]` rule is HTML-namespaced too. */
      icons.forEach((icon) => {
        icon.toggleAttribute("hidden", icon.dataset.mode !== mode);
      });
      button.setAttribute("aria-label", `Theme: ${mode}. Change it.`);
    };

    /* The button ships hidden and is revealed here, so a browser with scripting off shows
       no control at all rather than one that does nothing when pressed. */
    button.hidden = false;
    label();

    button.addEventListener("click", () => {
      mode = CYCLE[(CYCLE.indexOf(mode) + 1) % CYCLE.length];
      apply(mode);
      remember(mode);
      label();
    });
  });
})();
