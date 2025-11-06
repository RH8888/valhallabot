import {
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { LoadingOverlay } from '@/components/ui/loading-indicator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { DataTablePagination } from '@/components/data-table'
import { type UserRow, usersColumns } from './users-columns'

type UsersTableProps = {
  data: UserRow[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  isLoading?: boolean
  isFetching?: boolean
}

export function UsersTable({
  data,
  total,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  isLoading = false,
  isFetching = false,
}: UsersTableProps) {
  const table = useReactTable({
    data,
    columns: usersColumns,
    state: {
      pagination: { pageIndex: Math.max(0, page - 1), pageSize },
    },
    pageCount: Math.max(1, Math.ceil(total / pageSize)),
    manualPagination: true,
    onPaginationChange: (updater) => {
      const next =
        typeof updater === 'function'
          ? updater({ pageIndex: Math.max(0, page - 1), pageSize })
          : updater
      if (next.pageSize !== pageSize) {
        onPageSizeChange(next.pageSize)
      }
      if (next.pageIndex !== page - 1) {
        onPageChange(next.pageIndex + 1)
      }
    },
    getCoreRowModel: getCoreRowModel(),
  })

  const showLoading = isLoading || isFetching

  return (
    <div className='flex flex-1 flex-col gap-4'>
      <div className='overflow-hidden rounded-md border'>
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {showLoading ? (
              <TableRow>
                <TableCell colSpan={usersColumns.length} className='h-24 text-center'>
                  <LoadingOverlay label='Loading users…' />
                </TableCell>
              </TableRow>
            ) : table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className={row.original.disabled ? 'bg-muted/40' : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={usersColumns.length} className='h-24 text-center'>
                  No users found.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <DataTablePagination table={table} />
    </div>
  )
}
