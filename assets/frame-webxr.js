// SPDX-License-Identifier: MIT
// Prepare WebGL before a site's XR startup. Loaded by the per-title Android
// helper in each new document, including frames. No site or engine dependency.
(() => {
    'use strict';
    if (!isSecureContext || !/^https?:$/.test(location.protocol) ||
        typeof HTMLCanvasElement === 'undefined' || window.__frameWebXR) return;

    const state = {version: 2, contexts: []};
    const seen = new WeakSet();
    const original = HTMLCanvasElement.prototype.getContext;
    const descriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'getContext');
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
        ...descriptor,
        value: function(type, attributes) {
            if (!['webgl', 'webgl2', 'experimental-webgl'].includes(type)) {
                return Reflect.apply(original, this, arguments);
            }
            // WebIDL dictionaries also read inherited properties. Preserve
            // those and getter receivers, without mutating even frozen options.
            const options = attributes == null ? {xrCompatible: true} :
                (typeof attributes === 'object' || typeof attributes === 'function') ?
                new Proxy({}, {get: (_, key) => key === 'xrCompatible' ? true :
                    Reflect.get(attributes, key, attributes)}) : attributes;
            const context = original.call(this, type, options);
            if (context && !seen.has(context)) {
                seen.add(context);
                const actual = context.getContextAttributes();
                if (state.contexts.length < 32) {
                    state.contexts.push({type, xrCompatible: actual?.xrCompatible === true});
                }
            }
            return context;
        }
    });
    window.__frameWebXR = state;
})();
