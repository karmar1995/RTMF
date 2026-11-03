(function () {
  "use strict";

  var POLL_INTERVAL_MS = 5000;
  var FIRST_POLL_DELAY_MS = 400;
  var MAX_ATTEMPTS = 120;
  var REFRESH_REGION_SELECTOR = "[data-role='refresh-region']";

  function isFinalStatus(status) {
    return status === "done" || status === "error";
  }

  function isTerminal(status, statuses) {
    return statuses.indexOf(status) !== -1;
  }

  function setPollStatus(element, text) {
    var box = element.querySelector("[data-role='poll-status']");
    if (box) {
      box.textContent = text;
    }
  }

  function showFailure(element, message) {
    var alert = element.querySelector(".alert");
    if (alert) {
      alert.classList.remove("alert-info");
      alert.classList.add("alert-danger");
      if (message) {
        alert.textContent = message;
      }
    }
    setPollStatus(element, "");
  }

  function activateInjectedScripts(container) {
    Array.prototype.forEach.call(
      container.querySelectorAll("script"),
      function (injected) {
        var replacement = document.createElement("script");
        Array.prototype.forEach.call(
          injected.attributes,
          function (attribute) {
            replacement.setAttribute(attribute.name, attribute.value);
          }
        );
        replacement.textContent = injected.textContent;
        injected.parentNode.replaceChild(replacement, injected);
      }
    );
  }

  // -------- plot-state targets (`.mcf-plot-target`) --------

  function renderPlot(target, html) {
    var box = target.querySelector("[data-role='plot-box']");
    if (!box) {
      return;
    }
    box.innerHTML = html;
    box.classList.remove("d-none");
    activateInjectedScripts(box);
    setPollStatus(target, "");
    var alert = target.querySelector(".alert");
    if (alert) {
      alert.classList.add("d-none");
    }
    if (window.Plotly && typeof window.Plotly.Plots.resize === "function") {
      Array.prototype.forEach.call(
        box.querySelectorAll(".js-plotly-plot"),
        function (plot) {
          window.Plotly.Plots.resize(plot);
        }
      );
    }
  }

  function failPlotState(target, message) {
    target.dataset.plotStatus = "error";
    showFailure(target, message);
  }

  function applyPlotState(target, state) {
    var status = state[target.dataset.statusKey];
    var html = state[target.dataset.htmlKey];
    if (!status) {
      failPlotState(
        target,
        "The visualization service did not report a status for this plot."
      );
      return true;
    }
    target.dataset.plotStatus = status;
    if (status === "done") {
      if (html) {
        renderPlot(target, html);
      } else {
        showFailure(
          target,
          "The visualization service reported the plot as done but returned no HTML."
        );
      }
      return true;
    }
    if (status === "error") {
      showFailure(target, "Plot generation failed in the visualization service.");
      return true;
    }
    setPollStatus(target, "Current status: " + status + ". Checking again shortly.");
    return false;
  }

  function pollPlotState(target) {
    var url = target.dataset.plotStateUrl;
    if (!url) {
      failPlotState(target, "This plot has no status URL configured.");
      return Promise.resolve(true);
    }
    return fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("status " + response.status);
        }
        return response.json();
      })
      .then(function (state) {
        return applyPlotState(target, state);
      })
      .catch(function (error) {
        setPollStatus(
          target,
          "Could not read the plot status (" + error.message + "), retrying."
        );
        return false;
      });
  }

  // -------- page-content targets (`[data-poll-mode='page-content']`) --------

  function fetchPageDocument() {
    return fetch(window.location.href, {
      headers: { Accept: "text/html" },
      cache: "no-store",
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("status " + response.status);
        }
        return response.text();
      })
      .then(function (html) {
        return new DOMParser().parseFromString(html, "text/html");
      });
  }

  function swapPageContent(target) {
    var selector = target.dataset.refreshRegionSelector || REFRESH_REGION_SELECTOR;
    var region = target.closest(REFRESH_REGION_SELECTOR);
    if (!region) {
      return Promise.resolve(false);
    }
    return fetchPageDocument()
      .then(function (doc) {
        var fresh = doc.querySelector(selector);
        if (!fresh) {
          setPollStatus(target, "Could not read the updated page content, retrying.");
          return false;
        }
        region.innerHTML = fresh.innerHTML;
        activateInjectedScripts(region);
        // Re-run listeners the swapped-in scripts registered against the fresh
        // elements. Only those registered during this activation are pending.
        document.dispatchEvent(new Event("DOMContentLoaded"));
        return true;
      })
      .catch(function (error) {
        setPollStatus(
          target,
          "Could not reach the server (" + error.message + "), retrying."
        );
        return false;
      });
  }

  function pollPageContent(target) {
    var stateUrl = target.dataset.stateUrl;
    if (!stateUrl) {
      return swapPageContent(target);
    }
    var statusKey = target.dataset.stateStatusKey || "results_status";
    var terminalStatuses = (target.dataset.terminalStatuses || "done,error").split(",");
    return fetch(stateUrl, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("status " + response.status);
        }
        return response.json();
      })
      .then(function (state) {
        var status = state[statusKey];
        if (isTerminal(status, terminalStatuses)) {
          return swapPageContent(target);
        }
        setPollStatus(target, "Current status: " + status + ". Checking again shortly.");
        return false;
      })
      .catch(function (error) {
        setPollStatus(
          target,
          "Could not read the status (" + error.message + "), retrying."
        );
        return false;
      });
  }

  // -------- orchestrator --------

  function initPolling() {
    var plotTargets = Array.prototype.slice
      .call(document.querySelectorAll(".mcf-plot-target"))
      .filter(function (target) {
        return !isFinalStatus(target.dataset.plotStatus);
      });

    var pageTargets = Array.prototype.slice
      .call(document.querySelectorAll("[data-poll-mode='page-content']"))
      .filter(function (target) {
        return target.dataset.pollSettled !== "true";
      });

    var formControls = [];
    if (plotTargets.length > 0 && pageTargets.length === 0) {
      formControls = Array.prototype.slice.call(
        document.querySelectorAll(
          "#mcf-scatter-form select, #mcf-scatter-form button[type='submit']"
        )
      );
    }

    function allPlotsSettled() {
      return plotTargets.every(function (target) {
        return isFinalStatus(target.dataset.plotStatus);
      });
    }

    function syncFormLock() {
      var locked = !allPlotsSettled();
      formControls.forEach(function (control) {
        control.disabled = locked;
      });
    }

    syncFormLock();
    if (!plotTargets.length && !pageTargets.length) {
      return;
    }

    var attempts = 0;

    function tick() {
      // Drop targets removed by an in-place content swap. The freshly injected copy of
      // this script (activation re-runs it against the new DOM) continues the loop.
      plotTargets = plotTargets.filter(function (target) {
        return target.isConnected;
      });
      pageTargets = pageTargets.filter(function (target) {
        return target.isConnected;
      });

      if (!plotTargets.length && !pageTargets.length) {
        return;
      }

      attempts += 1;
      if (attempts > MAX_ATTEMPTS) {
        plotTargets.forEach(function (target) {
          if (!isFinalStatus(target.dataset.plotStatus)) {
            failPlotState(
              target,
              "Plot generation is still running in the visualization service."
            );
          }
        });
        pageTargets.forEach(function (target) {
          target.dataset.pollSettled = "true";
          showFailure(
            target,
            "The visualization service is still working; refresh the page to check again."
          );
        });
        return;
      }

      var remaining = plotTargets.length + pageTargets.length;
      var pendingCount = 0;

      function oneSettled() {
        remaining -= 1;
        if (remaining === 0) {
          syncFormLock();
          if (pendingCount > 0) {
            window.setTimeout(tick, POLL_INTERVAL_MS);
          }
        }
      }

      function track(promise) {
        promise.then(function (finished) {
          if (!finished) {
            pendingCount += 1;
          }
          oneSettled();
        });
      }

      plotTargets.forEach(function (target) {
        track(pollPlotState(target));
      });
      pageTargets.forEach(function (target) {
        track(pollPageContent(target));
      });
    }

    window.setTimeout(tick, FIRST_POLL_DELAY_MS);
  }

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }
  ready(initPolling);
})();