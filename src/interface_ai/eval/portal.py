"""Hermetic claims portal for HITL eval. Not the live CloudCruise demo."""

from __future__ import annotations

from urllib.parse import quote

CLAIMS_HTML = """
<html><body>
<form id="login">
  <input aria-label="Provider ID">
  <input aria-label="Password" type="password">
  <button type="button" aria-label="Sign in">Sign in</button>
</form>
<main id="app" hidden>
  <h1>Patients</h1>
  <input aria-label="Search patients">
  <table><tbody>
    <tr id="row">
      <td data-column="mrn">MRN-10042</td>
      <td data-column="patient-name">Jane Doe</td>
      <td data-column="status">Active</td>
      <td data-column="insurance">Acme</td>
      <td><button>Select</button></td>
    </tr>
  </tbody></table>
  <div id="summary" hidden>Patient Summary</div>
  <button type="button" aria-label="Recent Claims" aria-expanded="false">Recent Claims</button>
  <div id="claims" hidden><div>CLM-1 Pending</div></div>
</main>
<script>
document.querySelector('[aria-label="Sign in"]').onclick = () => {
  if (document.querySelector('[aria-label="Password"]').value === 'claims123') {
    document.getElementById('login').hidden = true;
    document.getElementById('app').hidden = false;
  }
};
document.querySelector('[aria-label="Search patients"]').addEventListener('input', (event) => {
  document.getElementById('row').hidden = !document.querySelector('[data-column="mrn"]')
    .textContent.includes(event.target.value);
});
document.querySelector('#row button').onclick = () => {
  document.getElementById('summary').hidden = false;
};
document.querySelector('[aria-label="Recent Claims"]').onclick = (event) => {
  event.target.setAttribute('aria-expanded', 'true');
  document.getElementById('claims').hidden = false;
};
</script>
</body></html>
"""


def claims_portal_url() -> str:
    return "data:text/html," + quote(CLAIMS_HTML)
