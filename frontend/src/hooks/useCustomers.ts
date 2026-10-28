// ============================================================
// OPSYN useCustomers HOOKS
// ============================================================

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { customersApi, type CustomerListParams } from '../api/customers.api';

export function useCustomers(params: CustomerListParams = {}) {
  return useQuery({
    queryKey: ['customers', params],
    queryFn:  () => customersApi.list(params),
    staleTime: 60_000,
  });
}

export function useCustomer(id: string) {
  return useQuery({
    queryKey: ['customers', id],
    queryFn:  () => customersApi.get(id),
    enabled:  !!id,
    staleTime: 30_000,
  });
}

export function useCreateCustomer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof customersApi.create>[0]) =>
      customersApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['customers'] }),
  });
}

export function useCustomerFields(id: string, stageOrder = 1) {
  return useQuery({
    queryKey: ['customer-fields', id, stageOrder],
    queryFn:  () => customersApi.getFields(id, stageOrder),
    enabled:  !!id,
    staleTime: 30_000,
  });
}

export function useSubmitCustomerFields(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ fields, stageOrder }: { fields: Record<string, any>; stageOrder: number }) =>
      customersApi.submitFields(customerId, fields, stageOrder),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['customer-fields', customerId] });
      qc.invalidateQueries({ queryKey: ['customers', customerId] });
    },
  });
}

export function useFormSchemas() {
  return useQuery({
    queryKey: ['customer-form-schemas'],
    queryFn:  () => customersApi.getFormSchemas(),
    staleTime: 5 * 60_000,
  });
}

export function useFormSchema(id: string) {
  return useQuery({
    queryKey: ['customer-form-schema', id],
    queryFn:  () => customersApi.getFormSchema(id),
    enabled:  !!id,
    staleTime: 30_000,
  });
}

export function useFieldDefs(schemaId: string) {
  return useQuery({
    queryKey: ['field-defs', schemaId],
    queryFn:  () => customersApi.getFieldDefs(schemaId),
    enabled:  !!schemaId,
    staleTime: 30_000,
  });
}

export function useCreateFieldDef(schemaId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: any) => customersApi.createFieldDef(schemaId, payload),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['field-defs', schemaId] }),
  });
}

export function useUpdateFieldDef(schemaId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldId, payload }: { fieldId: string; payload: any }) =>
      customersApi.updateFieldDef(schemaId, fieldId, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['field-defs', schemaId] }),
  });
}

export function useDeleteFieldDef(schemaId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fieldId: string) => customersApi.deleteFieldDef(schemaId, fieldId),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['field-defs', schemaId] }),
  });
}

export function usePublishFormSchema() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => customersApi.publishFormSchema(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['customer-form-schemas'] }),
  });
}
