/**
 * Printable document builder — shared by the customer flow (index.html) and
 * the back office (admin.html).
 *
 * Renders two things from the same layout:
 *
 *   receipt    work that was actually ordered. Carries the order reference,
 *              the client, and a status.
 *   quotation  a price offered but not yet accepted. Most quotes are this.
 *              It must NOT look like a receipt, or a customer could believe
 *              they had bought something they only asked the price of.
 *
 * One definition on purpose. Two copies of this template would drift the first
 * time a field or the logo changed, and the divergence would only surface on
 * paper, after a customer had already been handed the wrong thing.
 *
 * The document is fully self-contained: it is written into a new window with
 * document.write, which leaves it no base URL and no network access, so the
 * logo travels as a data URI and every style is inline.
 */

const fmtXAF = (n) => `${Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })} XAF`;
const prettify = (v) => String(v).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str ?? "";
  return d.innerHTML;
}

function row(label, value) {
  return `<div class="row"><span>${esc(label)}</span><span>${esc(value)}</span></div>`;
}

/**
 * Book typesetting reads as a sentence, not as seven separate rows of numbers.
 * A customer checking a receipt wants "Caveat 15pt / 1.7, justified", not a
 * field-by-field dump — and nothing at all if they left it to house style.
 */
function interiorRows(interior) {
  if (!interior) return "";
  const set = Object.entries(interior).filter(([, v]) => v !== null && v !== "");
  if (!set.length) return "";

  const bits = [];
  if (interior.typeface) bits.push(prettify(interior.typeface));
  if (interior.font_size_pt) bits.push(`${interior.font_size_pt}pt`);
  if (interior.line_spacing) bits.push(`/ ${interior.line_spacing} leading`);
  if (interior.text_align) bits.push(interior.text_align);

  let out = bits.length ? row("Typesetting", bits.join(" ")) : "";
  if (interior.paper_tone) out += row("Page colour", prettify(interior.paper_tone));
  if (interior.margin_mm) out += row("Margins", `${interior.margin_mm} mm`);
  if (interior.letter_spacing_em) out += row("Letter spacing", `${interior.letter_spacing_em} em`);
  return out;
}

function specRows(params) {
  const skip = new Set(["category", "urgency", "interior"]);
  const flat = Object.entries(params || {})
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== "" && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => row(prettify(k), Array.isArray(v) ? v.map(prettify).join(", ") : prettify(v)))
    .join("");
  return flat + interiorRows(params?.interior);
}

/**
 * Normalise an order receipt (POST /orders) or a quote document
 * (GET /admin/quotes/{id}/document) into the one shape the template renders.
 */
export function toDocument(src) {
  const isQuoteDoc = 'kind' in src;
  if (!isQuoteDoc) {
    return {
      kind: 'receipt',
      reference: src.order_id,
      dated: src.created_at,
      category: src.category, raw_query: src.raw_query,
      parameters: src.parameters, breakdown: src.breakdown,
      client_name: src.client_name, client_contact: src.client_contact,
      status: src.status,
      subtotal_xaf: src.subtotal_xaf, discount_xaf: src.discount_xaf,
      rush_fee_xaf: src.rush_fee_xaf, tax_xaf: src.tax_xaf, total_xaf: src.total_xaf,
    };
  }
  const o = src.order;
  return {
    kind: src.kind,
    // A receipt is referenced by its order; a quotation by the quote itself.
    reference: o ? o.order_id : src.quote_id,
    dated: o ? o.created_at : src.created_at,
    quoted_on: src.created_at,
    category: src.category, raw_query: src.raw_query,
    parameters: src.parameters, breakdown: src.breakdown,
    client_name: o ? o.client_name : null,
    client_contact: o ? o.client_contact : null,
    status: o ? o.status : null,
    subtotal_xaf: src.subtotal_xaf, discount_xaf: src.discount_xaf,
    rush_fee_xaf: src.rush_fee_xaf, tax_xaf: src.tax_xaf, total_xaf: src.total_xaf,
  };
}

/**
 * Build the printable HTML for one document.
 * `duplicate` stamps it as a reprint — a print shop should never have to
 * guess whether a second copy means a second payment.
 */
export function buildDocumentHtml(src, { duplicate = false } = {}) {
  const r = toDocument(src);
  const isQuotation = r.kind === 'quotation';
  const heading = isQuotation ? 'Quotation' : 'Receipt';
  const rows = r.breakdown.map(li => `
    <div class="row"><span>${esc(li.label)}</span><span>${fmtXAF(li.amount_xaf)}</span></div>
    ${li.detail ? `<div class="detail">${esc(li.detail)}</div>` : ''}`).join("");

  // A dedicated, self-contained print document — avoids relying on the
  // Tailwind CDN script re-rendering mid-print, which is unreliable across
  // browsers when combined with @media print + visibility tricks.
  const html = `
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>${heading} ${r.reference.slice(0, 8).toUpperCase()}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #12141C; max-width: 480px; margin: 24px auto; padding: 0 16px; font-size: 13px; line-height: 1.5; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #12141C;
    padding-bottom: 12px; margin-bottom: 16px; }
  .brand { font-weight: bold; font-size: 16px; }
  .mark { margin-top: 6px; }
  .sub { font-size: 12px; color: #5B6072; }
  .tag { font-size: 10px; letter-spacing: 0.05em; text-transform: uppercase; color: #9298A8; margin-bottom: 2px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .row { display: flex; justify-content: space-between; padding: 4px 0; gap: 12px; }
  .detail { font-size: 10px; color: #9298A8; margin: -2px 0 4px 0; }
  .divider { border-top: 1px solid #E4E6EC; margin: 12px 0; }
  .total-row { display: flex; justify-content: space-between; font-weight: bold; font-size: 16px;
    border-top: 2px solid #12141C; padding-top: 8px; margin-top: 8px; }
  .italic { font-style: italic; color: #5B6072; }
  .dup { border: 1px dashed #9298A8; color: #5B6072; font-size: 10px; letter-spacing: .08em;
    text-transform: uppercase; padding: 5px 8px; margin-bottom: 14px; text-align: center; }
  .footer { font-size: 11px; color: #9298A8; margin-top: 24px; padding-top: 12px; border-top: 1px solid #E4E6EC; }
  @media print { body { margin: 0 auto; } @page { margin: 1.5cm; } }
</style></head>
<body>
  ${duplicate ? `<div class="dup">Duplicate · reprinted ${new Date().toLocaleString()}</div>` : ""}
  <div class="header">
    <div>
      <div class="brand">Presprint PLC</div>
      <div class="sub">Limbe, Cameroon</div>
      <img class="mark" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAALQAAABwCAYAAAC3tFqQAAAz5klEQVR42u19eXgc1Z3tuVXVe6tbuy2M1JK8CNmxjROTYRljm8VmYjYnkckkJCQZePaQLwtkmSGECE3YAkxI4gkxM7yBZCATrAFilgc2GEvAxCGQGNuxhZCR1BYy2LKWbvXeVXXfH9W3VFVd1d1abBzo+336LHe31KWuU6fO/S3nR1Bcp8yiFAS3thKggwM6KQ4CpB1S7p+hHHY/U4be/y0Vh/vLSWx0FhGjXkqlcppKOIiUCBCHo4LGxj00ERGJ0ytQnp9l9ftIKnoMAMA7KXj7YT4dGZJ8p4/SVMJBPNU91OYdJt5ZYb7hjPex5uujhBDZ8thawGMhgEUtwIGFlLS1ySf6MyRFGH1A4AUIWlsJFrUR/AIEnZAIQE1f+/unK6R9z83G6DsNNHpsPpESAUipOkgJAlkKcHT0Y1Jc5I0/x7sEyezxGQOPu2ovAMDm6QdvP0zcFX+Qfae/I1bOfc/5+duOGMFOAYKV4FENiq2U5roYioD+q2BgyqGdkI5fgKzuhGh8PvH2AR//3I+auPC7c2ls+GxIqTqko/U0NrSUARQATiRIp7LYcWmPjbir9oLjg9RV/TLxVPek65a/6frC7e9mX9TggNYZY+8ioE80iFtbOaCNoA2yloEppRwevalB7nv1LBobPhupcICTjq+T4iJvBpDprvGwPO1zXeLj6LQZ3Vn2Mnx1L+KTm3YLF64f1oG7BRy2QiYEtAjoUw3ILS082tt1IBYfu3sOencuQ/jwRUiMns+Y90SBlAEwZKvn7G4PACDmqIIz830hKxGLwp0cAgCkYlH40/1yrvfOB3rtxSrzlc/CX/cCf8anniMbbunTa++psXYR0DMOZPDajZz42N1z0P3kFQgdvphG3r98pkArVzQSu9sDuaweqdIApLI6kIo5sLm8kCob4PE4EXLNgsfrmfG/MRqJwh8/img0Af54H1LvdoMfPQz7WBDcaD9coQOy8bitgM50PvHOfoqUNjzGtbz0NDnDHp0qsIuAnjFpAV4rK8Q7116K0UNfpaH+K6YK3hIfR+P+RRw5/WOIVC8DqZgDrnYxxMpAQUAdSAOIizhEOfWx7nCWdMd7craqqeH0wZXZnAi/14l5RAZcAgCg1mb93sn+g5AH9oM7tBvykYOoONahA3kugNPyxf/KNV70ILn6rndUYBcoRYqAnmFWFu9ceymO7f0Xq8iDFXjlikYizFkEbk4z0o3nQapsgKN+oTVYwwpQu8MigmMxAEB/OI1+iUM8mkK/dOJPLed1oIlTyDPgd6KBSyNQ6sY6P4dan2AKcunN5+HqewWe/mdVgFuBm5Qv2MwvumKzFtj5wphFQM8QmMUt1y9C7/Yf5WJkLYiF2sUk0bASttPPQHr++abgHUgDh2KyCloG2K5wuiCw5VpyJFkwaKf6e5p9NgT8Tqwqt6HJJ2C1n9M9L77xLKT9L4A78P/ADfdSM3DzLkGSXY3389fsvZmcYY/SFvBo12+wi4CeqSTIBnCkHVL6B8tuwNC+e3OBuMTH0Wj9Oi6x/HMoOeMsiFWNluDtGEkjGEqgW+Z0gNGCy+rxqQJ3JsCtfU/jsbL/N5V7sMbPY1Up0QFcfONZ2P/8WzgPPCaPh2ViBDZxV+1F9dIfCjdtf4bF8M20dRHQ02Xmm5p/Skfe/roZkBmIpRXXQli+LksyPBuSERyLoWNUUlm3UNAYl803+Z9Lh5PT/t3G38EuoEIusmafDavKeKyp86ngjkaiIC8+ANurW8AN91ItsFW2vuPgjYQQmba2ckZQFwE9hbVrJYTVnRCtwAwAiUVXcfE1N+mkxK6QjI4xih3BMXTL3IyDabK/r1FQdG6vmL1RbBQEOJw86niCnqiovsbsPdnvnMrxsNXEyVgTKMW1ZVTV3/ILW+B95hs6xuZdgiTbT3+Gfvqxr9rOXj5mBHUR0FOIL5P2dlOZMR6WiVC7mDiuvg+JBavUx1uDkgpim8+BRkHQgSgdTqKpXIlazPcI6IlOPNcritMCSiHAbvY6UMdnQ2F7KFEQyxdyd5jM37CmzI6N9S6s9nOIRqIQ2m+G8PK/6dga5XP/gCt+s84I6iKgJ5v1a2uj0pbrF9I9D+wzgplbchkhNzypA/LmvjCaOBnz55TpQMLYcb5H+ZeBuHskOiVwTgYwDIDGYzBbhyWKZEIyZXErVu+ahG7Pddxryuy4Z6EHtTZFY/v+a71eX5fP/YNwzV/W4Ax7DBQgBLQI6EnGmkkbJPF7c5/QRjOMYB4Ii9jwZgjdModLa/1oECh2hCQVPA2Ccj76RILtoUTe2/hkGdD4eu0dweu2IRJLF8SaZvLE4ZyIRJoBfa3ficMSnTFQA8Adcz3YVGuHMNQLafNnIA7sV9malC/YLNzZ9S22pykCerJS497PnIOe371qfH7o9lHO4/VgIA0s/d9RrCmz45LTPOiLSegTiQpitrYMJ9UTqQWO2WNTWUaQmL2HVVSiUD3fKAgquzMm1wLeauUDu/HiTIeT2FhBcOfiUkQjUXjv/lu4QgdkVVPPWvVp4abtz9CWFr4I6MlGNb4950ltCns8LBP6tW2ERTHO2ZfCfI+AC3wc+mISajgJTqcdfTEJDW4eiUQKv09l62QtSAI0DbvXpXt/9vpCNbVVuE4Nn2kSIsYVzMiiQjauS07zoY4nk5ImTLNPhsnT4STWlNnx26UeCEO9sN92hqwN6fEbD6/AGfZYEdAFrNZWcG1tkOOP3ny68PJdQeMmkP7LHoV1BxSw3l7HYecYELDLCKY4JBIpOJ12RWZkgM2+70wqt24mRewZhuuOyGp0YbKbwiZO1mXumnyCmrLOla6GRUby2ZCM92QeO0KSqvEZW6/1OwvaPOYCtxVrN3sd6uPpcBJyJIl/DDhx5+JSiG88C/KLK2iJj6O8S5Dk8o9/S/jh7vuFIlzzr1sB0gbA9s5Ll3OGonlpxUZwmcQIAzMwAeaAXQbsAgDl/6tKCYAMO9oJVgEIphQGZ0B+ZiCkB2i5JwvYTZwMlJYgQNNqJm4ekU1TzhluntLfXusTsMmnfN8GHrtCAjrGKB6Jy4jE0jgs0ayozWQWY2oracK0ezcUWfTLYALXB0TULl8HuuQyMr7vaZRA5Mlo37WU0i1Fhi6wu4QA1Cg3AGD0hjc5R/1CbBlI4T2ZR1tAwfrDQwqo57kVIB2KyQpLAmqx0Dy3wuTsAugYoyoLNpV7dBtIaIqGzNLIJ3oNpPXFSANhETcPcSo7azebZv9njwFALcepYcJC2J0xNbugmfTQsjQAkGUblxQZukAwJ4+IbtrmuDwr5pxJnHSMpLGxXlAr3IAJ0A2kFfDW2jjl+ZisgpmB/qjEY1WphD5RwMaaMvX92fMTYPqAmlXiIgbieub+tQ9oDTqwZTipAy+TEdDEt5mcSiUk2J085nDAoAwclhxIJiQcsxMV7FabSLZBfH5gHAMLPahdvg5ubWz62J6VRUDnF9AEbW2U+81VWcX4iYaVcGTYKkgm6OvBUYJVpTIG0hNA1LLbPDeHQzEZAfvE9wAQTHG4wDfxui9XTV0qnHDGzpShtgUE9ImKjjbVwxodbAR8HU9wsZ8H/Dy6I7IaLVHfQ5azWJ6tQzEZtX4O0fp1nLzvaYWl42MLioDOu9oIAJDQ4blGpSeV1akSIkCTAATsHAN2hCRcNssBgCqMrNWkGWAfArDarzB2MDWhuwGgY4yq0uVUXwNp4NdzOax6ewLMXrdNlRVGfex121SgdgHYHtKH//JFPWw+B5KRJLrDIlb77eA9XqjhDilVxxUBm2d1KNlUSsUq41OkYk5W0fzzR6II0DTGk9IEk9iUE68Ft1EDM2nRMUZx7WmnFpijkWhOKQIAKx0TYIzE0uiKJHFYoqjjCZq9DvWLPa9dvaKI7aEEeqLihFxBYVV/UjSiOZbQ/CKgC1xESgSMj4nlCkOzAnsACBIbmkqdKpgfOo4slt4VknW3zgsdogLwuIgaTlJZfCAsfuBAjkaiGJHzg4yFIo3ad3sooerorkjSUkJo4/FrTWLjTKqwqMe6DCEkYtEZiOV8lNYqpZCcRkdOMz5l9/gBKJ0iTaVOBFOcGqcNpjhVShhv0ezxgbCIYGqiu+MQ5dCU+f6DBjMAeLweeLwe5fhcmq88EQkGumavA2v9zqxIDfJkEc2Ymv2fRYDYZyaM9k+8SBDSRQ2dV0IrEo3wZJ7VaaFet0k/Hq8kUYTszQygaOedSQGJRAoDabuldo5GojPe6BqNRCEcD4I/3od0PAI6PIjw8WMg8RDkYcU6g44OTtydyuZAAEBOXwRSdhpwxt8iVbsEhyinhiJZHB1Q6lUcEq9u8g5LelDm2uwxpl7LC6jLMLU2o2jzObCxxq7+HVXpfhm+DHHYPP1FQBdoECN9o8oyxxYkNjRpTirLCppK8jGKBrcC7L4YBcCrUQ5jBGGmQJt6txvjAz2Qh98FHR0Ef7wHUiSesSbQX6Z2d3ZqgvYrhYV0z3NIxSjsbgJh2d+h7rqHUTunAgNhEZv7xtXsYaGxZVgkWhoEij7RPBbd7HVkoj9A5K3X4NRW3/H2w0VA5wEyIUSmAOH48SbJylpgbBzwl2b9fJ9IcIGPM2ygiBrN2BGSsMbPq0BnzG61KbNi6mT/QRW4kZ69EN/drwMtAy4DK/s7eK8LLq/+d1Xa46Y3ouMpFwEAlxeIH4vBPjqI2RkGvT8YKbjwSLtWOpTPSBsJYYzeFUlkVfqlw0m0ztXo6+Bf9OeLdwaLgM69FaQAkHpPcnJ5HIwa3LzutmsaO6UcWG+nUV/3iQSrKrNPx4js0KWzo5EoHG91YLh7H+Se30MefAvkWJ8paPlMgVOlPU5RbpYUjhf8SVTa4zQ6TkkkTVDz+a/D8ZWfAlDqVx4YplNKefeJhbF590gUNp8Dd8z16JJVjj8/oX9haeMfioAuYPFdT7smc8pYHQc0seeBHI3awRSHVCSKeVUOABxS4yHYqytUVj/6xkugb+6AvH8H+OM9CGmYl2iA6/IaGTaO6dp+ae9GtmUXouTKNjgWnQOANTBMFCs1myRRjBV2ipwoPO3N1qYKBzbV8iqYnQPdKD/yqr6L5W9v6ioCuhBAiwMQc5m5aFjWjH2Na56bQzCl30AqiBQwEBZx2FuGhW//GXT3VkivPQ7pWJ/Kvox5CwHudLzojN3qqfW3w5VJ8w+ERXy3L4kdoylLTdxsSHs3uHkMykrx1WSAnA4n8fUGX9ZmWd6zHdFxSkp8yi2PeGc/JZy9fKwI6Cmyl5VFl83n0DG0opezAc7kyXsyD2S+r7UBA3Fg4a+/BunF/1BBzHtdqC3PDeDpGikaQexpPo/Elv09UmeuIaSqUUnxp4EHj0jY3Deuq62w+bKZuSuSRJeGXV8Ky7pCplqOw4Cs3wxrIx+sEOkni8rUTaC6YXYJkF5+GJ4SMmF+6ap+GRhEEdAzaJKYisTRKNgQTHEZwJKCEhJa7W1/+h7En/p32N0Ermp3honjMw5e499R4uMot+QyQj+2Fqkz1xCxqhEcADEDogdHidplM5n2MLahYxs/bXE/A7CZVGkq92BrPYdaXzaYa/Y+i9jgXpTM4dXPgQRWbQX2FAE9U6svJukKlMyKacy+V4Gc0cFyz+9VVtbKiplmYADgllxGmPVYbPk6QjKXoJhh42ffT+FXo9AV9WsbcnOBudnrwMX+iaq6OlHWxZWTCQnNXqXSLpmQdDXVmyocOolhDGOOPHkPKjTsTPz124Tr7hukreCLgJ7hpZwUO2o4CX05+KJPJAjQNAA7+kSCObEwgFLT8NlUwawFcNy/iLMt+hjEhvMgB84gw6edBY/XAwqoR8m6UzpG0tglkSzgav9vFUe+OBOGTCUkdEdkvKBJimTVSEdEFcisxeqeBgdqfRZgdgmwv/I4xL+8ipJ6zWdSNu8/gXcArCRFQJ+g5XTagZSctXFUah5kHSunInHYS0vUDJ3XRlW5UiiYjewrzzmHE847D+nG8zBa2UAc9QtBM2o+AcCTOa6dY8BLYaXdS2uhwNjYqqPcLJrRKAjo5knWpo8B2Sw72CuKWOt34itznVkFW0ZmLk9GEdp2O2aVT/jaEXvZQemaZ1+iNwkEbZ1SEdC5VsdKnrZ0Uqnvrdl5JYdITDZ9JCs8pw3TAQB8ngyw6aQ2elp/Ci37js4/n2jtdgUTBmZNutq2Li2A83WNm621ficu8HF4/kg06++2SnOv9TvxlUrkBTJrKHj/wR/Aa9DOKG34seM0IUa3gicbUAR01gSqRQcJftGuDPFZ3SkCgDhv13V5N3cCRY8hgqEU5RDT+HSQ2NQa4FQkjppymxq+Y7t3K79ouaweyYYVoKc3EWegGbSqUWVfR+YLmLAe6x5L6CSEFqBmQLXSyKyFSttZonVceiksw+51oVHT0e5w8kgmpKxqOjMgW1b2uQSIbzwL+el74SnXaGd31d7eL/6xnXKExwbltid85MendXQCnZAUM+02HSPS7T+vkDp+eYuZf93xlIuUGhha2yhaw0lZRuKsA9zMYJyd0FnhfTQ6TomnhNDSWXYxPGutjW3cUoFmQqsaQQCwcihRw2o7kwL6YpKuO3uypo7NXoeudQoWbkrG0Jwlq0dEVY60VQlYN9tu2nmusLI5mKsHD2L4vs9hVjn0iZTqpT9csIAkFT+OdvqRALRie9vCYWG7UqyvB6+sK0B64GvNGH2nAeHDFyEVDohP3HD5dN9/HpFRa+NwSKutTVLkSkFTGkPnfYcItU1wNP0Neb8yYNNu3ESD2Xku9jWLRqTDybyhNqaNk4KAjTX2vMkQ7e8zWpI1CoKpdW7BhVguAeXJKIbvuxqz7HEdmEn5gs2KuQx40t6ufqDCh2ruH6UEGzYQLGwHDgJoZ2MM2nUISh4R3fxT32jQgle6sSYw3SE+2rir9qRgEvXHI9fchdkZBnNofKMZeIPEZsq+ZiDNMmQs0EODhdweHpXUCjertDazWNCaTuYDsfaOVOvzmEuNDJhDN68A+vfpohrEXnYQF93xI3rneoKtkLWSXfirnvmnAS9phwRCqNnQSvH1RxtJKHgW4mMLkAoHaJvjcnoCj61PJKixm6fHkaP+A+Dw7PuKJGHgzTaaSeUFs5lWTiYk9Bg86rThNKMmfiHjxdfsdagZPWPYjZkzruUFnGsXsW6ePYcviPkFrP6b2SSzYqxoZALM8+o5/QDPwMr/Y7tw/fDWlhZ+A9GTlfBXO3XVZAopG5umTltNjJ4v/urKpQAw0wCWInGE5cn1/gXscqb/kM9KqgRTHLYMpPD9d6I68OaSB7miEsbHu5HUuY5e7Ofx5TJFiQ/KSty4TyRIReJZCaKIwapsvkcBcJNP0Fgs2Gfkc631CRg/sBvhn34J5FifLkQHAKha8h3bdx7fTVdCIO3tWXpFOOUHVjL2bdNv2MSdT1bQPY8swFjv2SQVXoF0tJ6+dNNSzUWAE5rqrl+CROXcTOioBA0CzZYbyJ2AmW/x8RtBbAZqbUJiMps/BsjuiIxuwNRuTI6MQzcYSCMjZhrAxq6c2O9+gvGHvofZ5aAo14cuSfmCzcJte+6jKyGQTvN6MeHUkhCE4BgI6YSodWVnGzYytG8xjQ2fjcTo+XTrZ084eLUp4lRpQB3wI1YGcFrmBAyERWBsHH2esoJ+v1WEI2CX0Z3I3+GhjT70hsRJOZeyC05rNWY0deS8DlxSW2I56AcnoJvc41V0dPSX10N89VGVlXWu/a7G+zW2uZY7SeGUGRtskBDilusXYfD1ZRAjy6Uba86nsaGl9AQXGbECHRYmYxk2ogkoOTSbtYngfokah2axZTPgKjFoKa9rqJnk3pcBazLDln0i0ZVoHpaoWivRExV18V92R2CbSe0cFDbnJNc4thMJZACIv/IYIluuhRSJZ4fmAGjBjK2UgliHFIUPJgYMDm2QtSws7nyyAn/ccg7Chy9CZOhCuueBhScSvHJFIxGW6OcCxuoXEpJhfMHw4RhDZTtGU7hjrgdNPgG9YmpGLLrey6HJWUisVxTRmeTVFqUuE9BbraZyj2LumDnuk+2PZ5QX4wd2I9J+B+ie5xQg15tkRquWfEe4bc99FCBK1Irk5DXhpG3qWlo4tLezaaCSmrh47b+vQuTYRXTrZ684UXpXqF1MuPp6xBtWwH56E5yBZnWsWiHg3ZXxhdfrzGSmIkK5lRtT39D2EZqE7qz0tpXxuDbeu+9IOKcnNPsda8rsaCp1njDtiylaIyT7DyLU/mOIrz4KAKasrDcyzz2b8KQBmlLKYRXhSCdEZILf2tnX4hM3XM4b7GlnQjZE69dxWublM7LBmF0rJEkxXTf9Q5TDPENIz8qnooaT1KFCLLTGplBZmZ0z9/0mTsaqgPOkSofJrmT/QYw9vRnSi/+hAtmsZoW4q/bKTZ/+orDp/gNsDEih7yGcsLnXBwFCiARAppRy0l2XfAqjh75KX7pJx8STBbNZUXqqNAB53jngahfnlQ3a9LAZQLTgzRUWyzfCIV/TLItyDMrGbKGom2HSY5iGxQA/4Qvt/0Ckw2RW/JXHMLbzEdA9z+UEsjoOmc0hzBQcTea9hBMC5LYJSSG+8tCXpBtrvjjVLJwWwEz3xhtWgD/zEgxVBojH6zGrAMghG8ZzDuixihTknMU3Ng4UGOUwrjkc0K0pakoeCaPbcLE0lXuwqcKBmipBw772UxrEyf6DiP3+CcRfewLI+HpYAZl3CZJMyv6CDCvjTqIMaJokmGcM0OqY4AyQxS3XL0Jw13XiEzd8fbJhNeM8bPHM7HnYbk3EAYb0MJssZRXGMmsfyhXuKmgcRKaWGSY9g5NZqczFptW+evblT3kQS28+j9Cbu1Q2LgTIcnXzfwo37fo34H6oerlt8mCeNqCVzR44ojQjSwzIdM8DX59qZwXra0vPPx98/UJduMwoHVhhulE65CqNNJ3VV249UTVXWhkFFicVaiF4/RmlyrgF319PRUKy/yDG/vQi5P0vmILYUlrYyw5K3tr/lK9//QHHaUJMM79bms7xCNMdc4Z2SOJjd8/Bmw99t1AgG2WEfP6nwC++GENnrCIer0cX9zUCeIJ9x027KzCJAiI2gkz1MY6Ik5qaqmheOdNKVdhHyTaE7Bj6YhJSkQTm1SkDJmE7tcHMjG6Ov/kK5P07VDlRCIjZho96av4Lq3/4a9uF64dxmwBVKxuywScN0Kxkj1LKST86dxN96abNk2Xi0TOv5/jFF8OmGeouaCQEaw2aqA5L5axjsAK02XPGSU5dFnP3tBEGACqTG9k8SGxA5nVaIxUAeavtGtw8uscy4T2b4stxKjF0NBKFHNwHvmc3Qm/uAtfToTO6MdZa5AIyyhoelK595WHHaUIMt60HXQkBHZAyd/gZWcJURgOTdkjpn33uLOnGmgc4OvoxqQAgMzkhrbgWseXriBF+rLuiMzk5f7RCtK8R1FbgZ/MFgYmCHWgArj2udDiJvpgDAbvS7BoktgxTT1HnuoRTioGl/S9gJPgOuJ4OnUcevK6CmFgbtcDsRU8J3/yfl4D3gR8Kik7eCpkQiDM9nFuYlMRoa5MopVz6lo9/Cwfb76U5ErmMjeWKRpK+YhMc511JSFWj7g2nA2Jt+WIdr98ITkWCOJw8DksUD7yXyjuijNX9riolmEdkxRs6JKm9galIHCh1mpovFuKBd7I1sK3nZQy9tRfSodeyrMaMAAbi+UHsr98Gb/WLOO97jwkXrh9m90ANkKUTNWVeKHzGdbskPnb3HOmf5m2GZs61FZCF2sUkdvE/w7XiKtgM3RYPjhI1Dpyr5NFsFK9R+8JQvJM0vMZquqk2U9crikDEunKNjVhjJZOr/W5NrTMHjEq63sA+i6bXfFOmTrR+NrKv1uhxOgBmVlzw173AN67cTq6+6x3FVmC9AmK0gLS3S0rN+om9QIVCB7an7/3MOdzuWzqtEiEMyExW0OXroB3u+/AQ08SpvJu1Xp95algFZmbz1pXrwDOvafY6sNZgP2Js2TcD8Bo/j2VCEp8o0RatZ8d+jf1xWvuCXD7R2g3iiQKvcDwI6c3nMT7QY8q+xFQDJ2mhURnir99GSmq20gWXvyJc9b1BYBDAblCAdLSCX3UrlZXkWvtJu+MIhYBZvHPtpbTnd9tyyQuhdjFJX34byPJ1us3dr0eU7odCJAXzaFgjKNVk2pTvlG+pmWyb9ncYmdi85kEb8c69FGkB3XzuPpGg4SRqaGGoF+NvvQ7u0G5z7QugMlNjPFVbMeKd/RTsviCtWPiY/PnH9jpOE2IKE7+aacIAB7RS0tYmow1iZoDYSV2WnyJdCYG0QRRvOetq2v/ir3Jt9sjn/43QizfpgPzgkYn0cqGF72xYTGdSiXI7nDwGZBleuy3nCIN8F4kZgGey3ldh4uw7TyKRKiijxy4E1jCabwyFln2Zwbk2fIbM3iar22MKAKau6peJp7oHn9y0W9HDg8q98TvK5q5jIUiGiWW0QQLaPtA9gWAJ5k6I6R8su4Ee+/O9VmDmllxGhq57hLAPnzHyM0dTKpALmQO9VlPHy15rNloXOcbm5opyzDSAc0kI5s5v5Q0dsMvoiyHL5JFV7sHEqZ9p3/G39yDx9msq+2oNzqcNXnfVXtg8/dTuewWljX/A397UJZy9fEwBMABsV1h4JXhUt1BsbZfVcFvbqTNhW8iWGSsF0tYpineuvZT2v3ivFSunvvooca24Sj0NDw9BjRAwIBuLaqzagYwhMea2ozU2MYJb62KpBbXaedzgMJEQJ2YZQaxnbhNGdvJASNIzNCszjYsY6u2G3P8X4MCLptpXZV+DK/+kAGwvOwhv1U7irvgDrVqyn9/4i66JJos9AB6fAPDXWihatlJCiIxOiEA7cIpOiReyQ3PtYvrez5xDe363zUorj371UaI1v2ZDzK0YmbW6aw3+mJt7Z3ICzMYpSWbDz1l3cjIhYbumfd7mc2BThQOrTDzSPqhllBwM+KmElM3QdR44B7qR/tnfIz3D8kHLvsRT3cN/fN1usvYbw8DxzCteBTZl6igWAjjYggwDU3RCRGc7TlkEWwGatoJHW7tM/+eRKqnzW/9OLSQGveFJNS2tsLIMQM4pLXpFUTcSd1OFA30isGVY70qpZWkteLXpaS0Ts4vlmrnWjjwne81zc1r/GkymDUuOR5E6uHfadrqMfeEqfRvVyzr17GuQD6tWAlgls4SZ8nz7Xwt+czD0QYAAVPxj6wM0NbrQDMzkhifVx1qDyqbPLBVc6DivtRq/YBhKJrUx5sMS1RmkMFlxR0A45WuBJzN91Y0kJAOYC4oBu6v2wln2Mnx1L6Jy4R7huvsGJ9h3N7DpfmwF+JZWM/btBNCJD8sStIVGGd18RT4wf+kdGT1RSWdWYlU3obVSZQ6V2io5s+V129AVSeva9bWbRLOZGx+mlQ/MWgDz87/4Gvns1UPA+5nI/PaJrNxCAGiluLWNEgJJCUD89bJvQYCmlHIgRE4eEd245/R/MdPMNAvMYkGZPbaZa/Y68OUyXnWozAVm7QZQu9mrTlHUeh1onUV0o73Y8HRmUoKTPNB9xOExjXb0iSRvYsUYtsunj4l39lO05uy7+W//z2uKhOjSy4evtVAcWEhJW5s8IR/aPuhI2klm6FtXcQQQ0/eftdFYaFTi4+joVx9VC4kYmFmLPBslgPIJFmXDYGo5TicbmE9arsVYmEkKo0xhYDYC+WSAVzgehDywH+E3OyAdeg3o3wf+jj+idtHHVSPGqWQBA3YZDQJFrQ0Q4yMYzxETFv51cD3wOPAdolSqVbdQbNVEHzrb8VFfAto6lTLQG2u+qE1rj4dlkrzibuLORDNagxK2h5JoFAR0RZK6Tdmls+xIJfhMQkRh2AG3DSsdnK7wKF9smbF5F6AmVdb6nTgsUXy5jMdqP04KmFncN/Vut1oyyeK+VuODp7sG0kBNrhfMv+IHwP2gD3zCRjb+KU3U8BlBcWkATQAq3nXJOiM7C7WLCX/ljQCUqrgtw0md/RSbs3Gxn8e5ThkPRZTWVAbeq10cGtw8HolPxJMLSZRoQVzLcaoX8YWl2vHC+T0fMI2KM7OsmxmQSz3O7LmEmfHHZp0ryiTZyS9iLzvIb/xFF910PyEb/5QuwjZflCN8+CKjdiaXblRLVL4f1LfRs+qzwxJVBsOE9ImRZq8DDW7FjnUyKWsmLbSzn7siSWyqcOSdxsqcKz155mMbC9ZNK85gGCuMbLNzY50Eq4U+RDnUcGJO0xgUOMV14iwJaTNzyuIyAXRmM3i+Vm6U+Dg6dM4XiScTa+41JDB6RRG9oQxTmkwQZRvAOp4gmSf1rc0GGi+KLM1dgNRgLM2AzAAce+t1yPtfyEobEw2ACx0rXGmP06MGGtbOSbEyNTdeAAG74t7ZMTbxWmVgkGFxfBAAtraA39AOqQjbHIDmfnPVUq3FAAvTMUC8FJbzDiFnpZwsLAdA9ZuY7xHgkHKzldlmUZdAqXBMVKTFczu+e2yKt3Dkj8+D/OkppN/+PYjJaGGX1zg+LX5iP2mXAMTkTPaQ10U2zBoBzFZLEa8FaOjYkWWcwb0o3rAC7sxGxdgJYrYu8HG4vc6NnWNKNINlBAuRF7mGnXdFlPfcEZLQBl4dHWwKlrgI+yuP472XH9aVTjIadVW7NQDOPxtbO2XKrO6bNwm1aSMXiYQCUqNM0kqRYIrDPPdEEZPlpSpLASBjK1xceTR0fGyBsWjffnqT7hZvBea1fidur1MY+ebDsk77TrY6DiaF/mwT2j0SxZYBYFOtPQvIqWPD8Gy9B2TXL1QQS6YaeHID3vNl6CrtcSpqZAcb0M7S3toYtFb/G1uwtFNlpcoG3fxqdYmijVLKFXV0/sVBStUhhy+bVVsSA3OtTSkZZUyej53ZzI46nqCOJ6YTSVkGUqu9v/9ONKsj2v7Uz+G6fhbkp++FFImD97rUr0p7nJpt6KY7M5v9zNERELEykLPazupx1hCAAv36aGp0IXY/U6b6BRZXjkwhz89CTpMUfQaQTTZqcHPYOaactHOdQPckBtIA0GUb2cxnFkkxMrjN50DySBhL/ww8vsyP1X4F1PHqWRhb9neqwQnzFz6RQ96j45QAQMWVX4dDE0Ex1mVYgdks8cLYXKwMmBao8y5BkvY9NxvAMDZsKAaec2roRNhlPOvpeARCJpXMMnasu1op+QT6RCXDxYrVL/DxaBAcavsRkx+qiQuba2cmN0wMXoxWXZzXATmSxGf2hHDHXA821drhWnEVXCuuUi2oyIHnUXKsgzIAmo6SmAIjC7WLiVxWD25OM2w1S8HVLlZtyQbCIoIpYfIdLhnZUeLggRRVQ4zpikbCDfdmp72H9i0GcAALi9nA3Azt9MURG9I9SIcHofWq2B5KqI2mrOSzS1Pi2RVJojGkMLfdyeMCbsLXYkdILLgSj4HY67YhYtJ5whw//3nvCH7VZ8M/zXXhyjluBVz1C4Erb8RQJMoJx4Pgj/ch9W43+NHDsI8F4UqPIBkx91V2eH2I28rBe7ygpbWQyuogl9VCqmxQDSGZo6nLxBBSOyF2smsWT/EX7QmZswjycC+MDq0kNnw2gN+iA0WGzsnQqeixrNrngR61PfT2Og7b9ysamZV7alPVXRrd2ycSICIDXg7dEaUibzINroyRtRrczPWT8zrQLQNf3hNG8ztxrAmUqsaGHq8H8CoAFzSuTLnEUCITDZHVjYXyJZhYkv1pPIUxuxsBu4x5xFpizHNzug2f2XhkNspNu+INKyD+71OkxGco6E+Mng8A6CxGOnJHOey+IO86rgvbkfe7MJBWdue1NmBThUNl5rUWWjmZcRlqECjmcEBKoEjRNHpnmFC0LvUM2N19YWw2dHAvE5Lwe53KJNdJVOEx1u0OixPzAkMJdIXT6kSoOwJyppBfb2bOAKw8NzFF1jqsJ2R+hlM3vO4rbwTtewXj+57WhQ1pbGgp3f7zCrL2G8PFiEcuQLtK3zZGtCqOvEr7jw0TzKkAALQFeHQmHSpLb6pwZLkd9YoiEIViGZABf6NgQ6MAXd8g2wAW4k5kasaYmTXCnOuNa8doCs8PjGdAr9frTZw1BrrC+VP0a8rsWFUG0z7FgXRmE+0SJsJ0LkEXh2ZAR1xUPaG1ESVkQE1ueBLcfevJ+L6ndRtb6c/PngPgGbQXN4bWGtofeF0a/KMu7f3+oMR5uzswUHKFym7/1cBjQ5eggnqlg6KOd+pMW7qR1A24Yf/vFRXXeVWyeATMhwJy46SmQsdA5HLQt3quENCqs/k4WWVlQGkquPY03rLNy+gcqn2dFtS1NmAAApxJqCInYJczEgU4FJKx2s8hdt0jqLq5jOoiHdFj8wEAB4obQ8tzJ5z1hV7eJWTpMtr7usIwGa+IWhuwtdmORkEB9ZbhJHqiIuZ7BF3tstabWcusRkbWJmF6RTGnEYzWXT+Xd50cSWbN3TMClX1NZjVxMjb3hbFh9zBu2j+GXSG5oHHHWhCzL/Z/BmJtC1kwpUwcYBGPxKKrOBapkeIiT1LhFZma/aLcsDrH5NzLhmW+8lntg54SQuX9O9RMoRmo0+GkysxaUGvHOpgBtCcqoicqIpmQspInVhtBr9umA7HZe2gBawZy41c+nc7YXI4k0S0roOuWOfwymMAD/XEcik0O1Ma12j8hW5gUCdhlXDtByqCltYarOlqfSedT+qFupJpuT6Gr+mVeOr5OlwLv3wf7G9uQWvEZIC6qm5ZaG7B7iR2tQR6b+8J4ZiCkDrJhdgVWZoepSBzdo6mCnUHZ66pTFOdlaqSTgpC3Kdcs1DfZxd6bySS2EW4s9+CSGjtW+2f+ZChsPcHYUXulLspCY0NLE28f8DkXLAqDUoI8M/s+mqlvAGLzp9qN5aNeGwXZuTkrAsBWW4DH3o+XYE2ZXWVrrckM08xr/U5srLGjQaDq4J58m0EzBmZ62yhPcgEy30iKXF9aMEOTJd1YY59oNpihpZUjeRmo88HMQJcimM0WycxOlsRvz3mSRt6/XJvuPToCwn/zMZWlrZpRd4VkPNAfx47RlAoW5oqkTfFqDRjzsWyW3e0MLK0db64CKWPTL2tqYMbma/w8ajgJTYbPQRvlmM5id8PR39wG/olWzJ7Dq5o5Vraq2n/XzmFKQTJDTItLJzlaWoD2dqDyY/8XGkADilvP0W23Eyy/wpSpGbBX+zmsXurBrpALOw6H8cCwEuHoHtHLDoeT1418aExMpNRh0jWdrzvcCqwrHdlDLo3fGxsPrDai0Iyx6AbQVG5Dn0jQBwG/Ck5EeJrKPbimDFjnyg7nmdnuWgFZu9zJ4zAeFamsLmrnXAytTrOilEg31rxhLPY/OgLCX3QdUpt+aVpcX84lTfv4tgyk0DGSVlk71/xqswIoWHlDFwBqM+dR43tpnZ6MPnx5ox6aqE73SBRyJInmunJsrLGr0YtCWToaiWJEzpZGtT4B7916GaqDz+nGBkvf3lfmXLAoXEyu5AI0M5r52WcvoAeffAGGSrOjIyD8l36C1OXfsOwYsQK2dvTEjuCYGjGYygZNO4ICBgNzbZvYVBcDqhVzG6MjnNehZiaZBCnUycnIxmafZ/S7i1GROKwCmtjLDvI/H1pKCJGp0u9dlBxmgJ6YbAVJ/N7cJ6hm5ASLgx4dAeFv2YHU0gvy9vblSzXvCsnoDovoGEkjGEqgW+YsQ2lWUQomYbSWCphGGt3scQBo9tmA0hIEaFoF7jo/N2mtbMXEVp/f+IHdGP/+Csyrn0hvMm+OIpgL8bZbmJEen2zbSF/9h0tZ1KPEx9HxsExmlYMev+8KYr9hW15QM/axYu3Vfg6r/fZMB4onq4YiOBZDn6yghQHeOKzdaqREvhgzA28TJwM+GwKZSAYD62xOhN/rN6kBsU97mms5lywY1GLHQ7qGWd4lSJKr+mVgEGgFh7ZikVJOhjbxuNtmJj0AwCzyUSjzTNeMhb1noR4X8zQy84Oe/6fah+UCtUtA9eBBjN38N6i0x3X6GQtbzrZ987evb21p4Te0txcBnQ/QWumR/sGyG/jIwR8b3ZSYJwV32XeQvuYuFGIvUM7pWXMqZjAfhlUIoGt9Ao7dvAoVR17VgZm4q/byP3lvOUumFCVHjsSKDuHtkOhKCLbb9twnuxrvh6F7o9Iep7zXBfnpeyHcfhmcA915B95oT+BHFcwoxObAJeDYPddA/Muruio73iVIKGt4kBAioxVcEcyTYGjdUPp2SOJNzT/l4r3XG5mabRQBgN/wI6Qu+25O3wzG0h9lQFtuDDOfm/CT9aB7nsOsclBjP2R0/StV/kvOHQWlpBiumwRDq7ezrZBpC3jhzq5vSd6F/2TW+TyrHJT3uiBtvQX8LZ+E66WHdGxjJTmKS8/K9lceh/0fyyzBzJ1+zhdKLzl3BC0oxp6nwtCmTH3n2ku5ox1PGD08jGyN+iXgz/8yvGv/AR6vR93IaUH9UWNppp2Zn3StTYnq2N/YBmnb7UD/PrVb3QhmUr5gs3Bn17fY3qYI2WkA2jjmTdxy/SL0bv8Rl3r30nzA5r0u4OyrgXNa4D3jb3QgtjJS/CgAOxLsBt29FfL+HarLqRmYeZcgyfbTn+F/fOiz2EBIZkZ2UTvPBKABgG4FTzZA8ZL+0bmbuJE//xRQCs/NgK1z6KxfAm7xGpAz12SB+8O+kv0HMdbbpY5o01r1WrEy7xIk2dV4P3/HwRtBCIWSSSmCeSYBrR2VDADiY3fPwZsPfZeL916fC9g6OZJhbnLmp0EbP4HST1wEsTLwoQA4c/nnj/dhOPgO5P0vgI4OZnlN5zPC4V2CJJd//FvCD3ffrzglFavqThigjbFqAGAyhIb6r+ANpo/5wM0ALs9fBXL6IvibloGrXXzKgpyBNhUNQRg5DDo8iPGBHsjD71r6TGcPh7d2cyLlCzbjzK/cI1z1vUGlYKzIzCcF0Opcw4MTjpjpn33uLPL+3i9YMbaVb5sR4AzkUuV8kLI54CpOR0ntfDg9bshltYi7ymH3+OHxOBFyzZoW8JmWF44HAQCpaAiu+AjS8Qjo8CDCx4+BxEOQh98FHR0Ef7wnayB8LvAWaklGyhdsprOXPmr75m9fNxJGcZ0kQE8Au5VDWxtlwX66/ecV0mv/fRVG+66lsaGlVqxtBfBcQDdz2FdcO+dP7phj4xBi70/8fKQwb2grwE7FBJK4q/airOFBNK3fJlz1vUHtKDZSrNP44ABtxdhMjpBjf7yajr67thBwFwr2yYJfu7w2irjDbTluYiadSrM+bH/9NnirX0T1sk5h0/0HtBKuCORTDNDqyaGUw62EGE+OuOX6RTi2ZyVChy+GLAWmAvCpAn4mnUgnNZ7Y7jgEf90L8M95Cx/7wl7hwvXDWSRwK6XFZMkpDOgsOdLRxikjyPSgF3/+958goeBZiI8tQGL0fNYpwzxCpgP0E7nMjs84HB5lc/uy52tnElWt4IBWStraiiD+awN0FrjRRoyyRGXwnU9W0D2PLODiRwNyMlpD4sfOZ+MYtG1hMwVI45LiIm92xyD2soMQhDQ4Pgi7L0h5ZxAAGHDpmV8dtJ29fMwy09oKDotagJatRSb+MAFaz9Ag2NDCYWE70AGCTkhWFWSUUk566Xdl6HlhNo0c9ZF0pAKxkVK4vaU0OmYjUiIAKVUHKaH8LbyTkhLvbDmWrY9JKnqMvUbpACnrllPSMc7OV1PYBgjhR6jgiVB32VHiKI+hrH6M3/Dd9/IBkZUIKLO1VxJglZyZr10MuZ3k9f8BXgOmGHFzoGcAAAAASUVORK5CYII=" width="86" height="54" alt="Presprint">
    </div>
    <div style="text-align:right">
      <div class="tag">${heading}</div>
      <div>#${r.reference.slice(0, 8).toUpperCase()}</div>
      <div class="tag" style="margin-top:6px">Line</div>
      <div style="text-transform:capitalize">${esc(r.category || "")}</div>
    </div>
  </div>

  <div class="grid">
    <div>
      ${isQuotation ? `
        <div class="tag">Prepared for</div>
        <div class="sub">Not yet assigned to a client</div>
      ` : `
        <div class="tag">Client</div>
        <div>${esc(r.client_name || "Walk-in client")}</div>
        <div class="sub">${esc(r.client_contact || "")}</div>
      `}
    </div>
    <div style="text-align:right;">
      <div class="tag">${isQuotation ? "Quoted" : "Date"}</div>
      <div>${new Date(r.dated).toLocaleString()}</div>
      ${isQuotation ? "" : `
        <div class="tag" style="margin-top:6px">Status</div>
        <div style="text-transform:uppercase">${esc(r.status)}</div>
      `}
    </div>
  </div>

  <div class="tag">Order Request</div>
  <div class="italic" style="margin-bottom:12px">${esc(r.raw_query || "(manually specified)")}</div>

  <div class="tag">Specification</div>
  ${specRows(r.parameters)}

  <div class="divider"></div>
  ${rows}
  <div class="divider"></div>

  <div class="row"><span>Subtotal</span><span>${fmtXAF(r.subtotal_xaf)}</span></div>
  <div class="row" style="color: #16A34A;"><span>Discount</span><span>− ${fmtXAF(r.discount_xaf)}</span></div>
  <div class="row"><span>Rush fee</span><span>${fmtXAF(r.rush_fee_xaf)}</span></div>
  <div class="row"><span>Tax</span><span>${fmtXAF(r.tax_xaf)}</span></div>
  <div class="total-row"><span>Total</span><span>${fmtXAF(r.total_xaf)}</span></div>

  <div class="footer">
    ${isQuotation
      ? "This is a quotation, not a confirmation of order. The price above is based on the specification shown and may change if the specification changes. Nothing has been charged."
      : "Thank you for your order. This receipt confirms your order has been received and is pending production."}
  </div>
</body></html>`;

  return html;
}

export function printDocument(src, opts = {}) {
  if (!src) { alert("Nothing to print."); return false; }
  const html = buildDocumentHtml(src, opts);
  const printWindow = window.open('', '_blank', 'width=600,height=800');
  if (!printWindow) { alert("Pop-up blocked — please allow pop-ups for this site to print the receipt."); return false; }
  printWindow.document.open();
  printWindow.document.write(html);
  printWindow.document.close();
  // Wait for layout before printing, otherwise some browsers print a blank page.
  printWindow.onload = () => { printWindow.focus(); printWindow.print(); };
  return true;
}

/** Back-compat alias for the customer flow, which only ever prints receipts. */
export const printReceipt = printDocument;
export const buildReceiptHtml = buildDocumentHtml;
