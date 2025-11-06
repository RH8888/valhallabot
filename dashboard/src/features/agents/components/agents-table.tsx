import { useEffect, useMemo, useState } from 'react'
import {
  type ColumnFiltersState,
  type SortingState,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { cn } from '@/lib/utils'
import { type NavigateFn, useTableUrlState } from '@/hooks/use-table-url-state'
import { DataTablePagination, DataTableToolbar } from '@/components/data-table'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { LoadingOverlay } from '@/components/ui/loading-indicator'
import type { Agent } from '@/lib/api/types'
import { agentsColumns } from './agents-columns'

type AgentsTableProps = {
  data: Agent[]
  search: Record<string, unknown>
  navigate: NavigateFn
  isLoading?: boolean
}

export function AgentsTable({ data, search, navigate, isLoading = false }: AgentsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})
  const [columnFiltersState, setColumnFiltersState] = useState<ColumnFiltersState>([])

  const { columnFilters, onColumnFiltersChange, pagination, onPaginationChange, ensurePageInRange } =
    useTableUrlState({
      search,
      navigate,
      pagination: { defaultPage: 1, defaultPageSize: 10 },
      globalFilter: { enabled: false },
      columnFilters: [
        { columnId: 'name', searchKey: 'name', type: 'string' },
        {
          columnId: 'active',
          searchKey: 'status',
          type: 'array',
          deserialize: (value: unknown) => {
            if (!value) return []
            if (Array.isArray(value)) return value
            if (typeof value === 'string') return [value]
            return []
          },
        },
      ],
    })

  useEffect(() => {
    setColumnFiltersState(columnFilters)
  }, [columnFilters])

  const table = useReactTable({
    data,
    columns: agentsColumns,
    state: {
      sorting,
      pagination,
      columnVisibility,
      columnFilters: columnFiltersState,
    },
    onSortingChange: setSorting,
    onPaginationChange,
    onColumnFiltersChange: (updater) => {
      onColumnFiltersChange(updater)
    },
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  useEffect(() => {
    ensurePageInRange(table.getPageCount())
  }, [ensurePageInRange, table])

  const statusFilterOptions = useMemo(
    () => [
      { label: 'Active', value: 'active' },
      { label: 'Inactive', value: 'inactive' },
    ],
    []
  )

  return (
    <div
      className={cn(
        'max-sm:has-[div[role="toolbar"]]:mb-16',
        'flex flex-1 flex-col gap-4'
      )}
    >
      <DataTableToolbar
        table={table}
        searchPlaceholder='Search agents...'
        searchKey='name'
        filters={[{ columnId: 'active', title: 'Status', options: statusFilterOptions }]}
      />

      <div className='overflow-hidden rounded-md border'>
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className='group/row'>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} colSpan={header.colSpan}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={agentsColumns.length} className='h-32 text-center'>
                  <LoadingOverlay label='Loading agents…' />
                </TableCell>
              </TableRow>
            ) : table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id} className='group/row align-top'>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className='align-top'>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={agentsColumns.length} className='h-32 text-center'>
                  No agents found.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <DataTablePagination table={table} className='mt-auto' />
    </div>
  )
}
