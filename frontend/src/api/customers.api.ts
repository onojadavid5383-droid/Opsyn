// ============================================================
// OPSYN CUSTOMERS API — src/api/customers.api.ts
// ============================================================

import apiClient from './client';

function toCamel(s: string): string {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}
function camelizeKeys(o: any): any {
  if (Array.isArray(o)) return o.map(camelizeKeys);
  if (o && typeof o === 'object')
    return Object.fromEntries(Object.entries(o).map(([k, v]) => [toCamel(k), camelizeKeys(v)]));
  return o;
}

export interface CustomerListParams {
  status?:        string;
  source_app?:    string;
  date_from?:     string;
  date_to?:       string;
  department_id?: string;
  page?:          number;
  page_size?:     number;
}

export const customersApi = {
  list: (params: CustomerListParams = {}) =>
    apiClient.get('/customers/', { params }).then(r => camelizeKeys(r.data)),

  get: (id: string) =>
    apiClient.get(`/customers/${id}/`).then(r => camelizeKeys(r.data)),

  create: (payload: {
    first_name: string; last_name: string; email?: string; phone?: string;
    address?: string; source_app?: string; external_ref_id?: string;
    assigned_department_id?: string; amount?: number; currency?: string;
  }) => apiClient.post('/customers/', payload).then(r => camelizeKeys(r.data)),

  getFields: (id: string, stage_order = 1) =>
    apiClient.get(`/customers/${id}/fields`, { params: { stage_order } }).then(r => camelizeKeys(r.data)),

  submitFields: (id: string, fields: Record<string, any>, stage_order = 1) =>
    apiClient.patch(`/customers/${id}/fields`, { fields, stage_order }).then(r => r.data),

  importRows: (rows: any[]) =>
    apiClient.post('/customers/import/', { rows }).then(r => r.data),

  exportCsv: (params: { status?: string; source_app?: string } = {}) =>
    apiClient.get('/customers/export/', { params, responseType: 'blob' }),

  // Form schemas for customer pipeline (from /api/v1/forms/schemas)
  getFormSchemas: () =>
    apiClient.get('/forms/schemas').then(r => camelizeKeys(r.data)),

  getFormSchema: (id: string) =>
    apiClient.get(`/forms/schemas/${id}`).then(r => camelizeKeys(r.data)),

  createFormSchema: (payload: { title: string; context: string; department_id?: string; description?: string }) =>
    apiClient.post('/forms/schemas', payload).then(r => camelizeKeys(r.data)),

  updateFormSchema: (id: string, payload: any) =>
    apiClient.put(`/forms/schemas/${id}`, payload).then(r => camelizeKeys(r.data)),

  publishFormSchema: (id: string) =>
    apiClient.post(`/forms/schemas/${id}/publish`).then(r => camelizeKeys(r.data)),

  // Field definitions
  getFieldDefs: (schemaId: string) =>
    apiClient.get(`/forms/schemas/${schemaId}/fields`).then(r => camelizeKeys(r.data)),

  createFieldDef: (schemaId: string, payload: any) =>
    apiClient.post(`/forms/schemas/${schemaId}/fields`, payload).then(r => camelizeKeys(r.data)),

  updateFieldDef: (schemaId: string, fieldId: string, payload: any) =>
    apiClient.patch(`/forms/schemas/${schemaId}/fields/${fieldId}`, payload).then(r => camelizeKeys(r.data)),

  deleteFieldDef: (schemaId: string, fieldId: string) =>
    apiClient.delete(`/forms/schemas/${schemaId}/fields/${fieldId}`).then(r => r.data),
};
