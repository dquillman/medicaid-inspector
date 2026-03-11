import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../lib/auth'
import { get, mutate } from '../lib/api'

interface UserRecord {
  username: string
  role: string
  display_name: string
  created_at?: number
}

const ROLE_LABELS: Record<string, string> = {
  admin: 'Admin',
  investigator: 'Investigator',
  analyst: 'Analyst',
  viewer: 'Viewer',
}

const ROLE_COLORS: Record<string, string> = {
  admin: 'bg-red-900/50 text-red-400 border-red-800',
  investigator: 'bg-purple-900/50 text-purple-400 border-purple-800',
  analyst: 'bg-blue-900/50 text-blue-400 border-blue-800',
  viewer: 'bg-gray-800 text-gray-400 border-gray-700',
}

export default function UserManagement() {
  const { token, user: currentUser } = useAuth()
  const [users, setUsers] = useState<UserRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Create user form
  const [showCreate, setShowCreate] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState('viewer')
  const [newDisplayName, setNewDisplayName] = useState('')
  const [creating, setCreating] = useState(false)

  // Edit state
  const [editingUser, setEditingUser] = useState<string | null>(null)
  const [editRole, setEditRole] = useState('')

  const fetchUsers = useCallback(async () => {
    try {
      const data = await get<{ users: UserRecord[] }>('/auth/users')
      setUsers(data.users || [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setCreating(true)
    try {
      await mutate<{ ok: boolean }>('POST', '/auth/users', {
        username: newUsername,
        password: newPassword,
        role: newRole,
        display_name: newDisplayName || newUsername,
      })
      setSuccess(`User "${newUsername}" created successfully`)
      setShowCreate(false)
      setNewUsername('')
      setNewPassword('')
      setNewRole('viewer')
      setNewDisplayName('')
      fetchUsers()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create user')
    } finally {
      setCreating(false)
    }
  }

  const handleUpdateRole = async (username: string, role: string) => {
    setError('')
    setSuccess('')
    try {
      await mutate<{ ok: boolean }>('PATCH', `/auth/users/${username}`, { role })
      setSuccess(`Updated ${username}'s role to ${ROLE_LABELS[role]}`)
      setEditingUser(null)
      fetchUsers()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to update user')
    }
  }

  const handleDelete = async (username: string) => {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return
    setError('')
    setSuccess('')
    try {
      await mutate<{ ok: boolean }>('DELETE', `/auth/users/${username}`)
      setSuccess(`User "${username}" deleted`)
      fetchUsers()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to delete user')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-500">Loading users...</div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">User Management</h1>
          <p className="text-sm text-gray-500 mt-1">{users.length} user{users.length !== 1 ? 's' : ''} registered</p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="btn-primary"
        >
          {showCreate ? 'Cancel' : '+ New User'}
        </button>
      </div>

      {error && (
        <div className="bg-red-950/50 border border-red-800 rounded-lg px-4 py-3 text-sm text-red-400 mb-4">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-950/50 border border-green-800 rounded-lg px-4 py-3 text-sm text-green-400 mb-4">
          {success}
        </div>
      )}

      {/* Create user form */}
      {showCreate && (
        <form onSubmit={handleCreate} className="card mb-6 space-y-4">
          <h2 className="text-lg font-semibold text-white">Create New User</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1.5 uppercase tracking-wider">Username</label>
              <input
                type="text"
                value={newUsername}
                onChange={e => setNewUsername(e.target.value)}
                className="input w-full"
                placeholder="jsmith"
                required
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1.5 uppercase tracking-wider">Display Name</label>
              <input
                type="text"
                value={newDisplayName}
                onChange={e => setNewDisplayName(e.target.value)}
                className="input w-full"
                placeholder="Jane Smith"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1.5 uppercase tracking-wider">Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                className="input w-full"
                placeholder="Min 6 characters"
                required
                minLength={6}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1.5 uppercase tracking-wider">Role</label>
              <select
                value={newRole}
                onChange={e => setNewRole(e.target.value)}
                className="input w-full"
              >
                <option value="viewer">Viewer</option>
                <option value="analyst">Analyst</option>
                <option value="investigator">Investigator</option>
                <option value="admin">Admin</option>
              </select>
            </div>
          </div>
          <div className="flex justify-end">
            <button type="submit" disabled={creating} className="btn-primary">
              {creating ? 'Creating...' : 'Create User'}
            </button>
          </div>
        </form>
      )}

      {/* Users table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left py-3 px-4 text-xs text-gray-500 uppercase tracking-wider">Username</th>
              <th className="text-left py-3 px-4 text-xs text-gray-500 uppercase tracking-wider">Display Name</th>
              <th className="text-left py-3 px-4 text-xs text-gray-500 uppercase tracking-wider">Role</th>
              <th className="text-left py-3 px-4 text-xs text-gray-500 uppercase tracking-wider">Created</th>
              <th className="text-right py-3 px-4 text-xs text-gray-500 uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.username} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="py-3 px-4 text-white font-mono">
                  {u.username}
                  {u.username === currentUser?.username && (
                    <span className="ml-2 text-[10px] text-gray-500">(you)</span>
                  )}
                </td>
                <td className="py-3 px-4 text-gray-300">{u.display_name}</td>
                <td className="py-3 px-4">
                  {editingUser === u.username ? (
                    <select
                      value={editRole}
                      onChange={e => setEditRole(e.target.value)}
                      onBlur={() => {
                        if (editRole !== u.role) {
                          handleUpdateRole(u.username, editRole)
                        } else {
                          setEditingUser(null)
                        }
                      }}
                      onKeyDown={e => {
                        if (e.key === 'Enter') handleUpdateRole(u.username, editRole)
                        if (e.key === 'Escape') setEditingUser(null)
                      }}
                      className="input text-xs py-1 px-2"
                      autoFocus
                    >
                      <option value="viewer">Viewer</option>
                      <option value="analyst">Analyst</option>
                      <option value="investigator">Investigator</option>
                      <option value="admin">Admin</option>
                    </select>
                  ) : (
                    <button
                      onClick={() => {
                        setEditingUser(u.username)
                        setEditRole(u.role)
                      }}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded border cursor-pointer hover:opacity-80 ${ROLE_COLORS[u.role] || ROLE_COLORS.viewer}`}
                      title="Click to change role"
                    >
                      {ROLE_LABELS[u.role] || u.role}
                    </button>
                  )}
                </td>
                <td className="py-3 px-4 text-gray-500 text-xs">
                  {u.created_at ? new Date(u.created_at * 1000).toLocaleDateString() : '--'}
                </td>
                <td className="py-3 px-4 text-right">
                  {u.username !== currentUser?.username && (
                    <button
                      onClick={() => handleDelete(u.username)}
                      className="text-gray-600 hover:text-red-400 transition-colors"
                      title="Delete user"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                      </svg>
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Role legend */}
      <div className="card mt-6">
        <h3 className="text-sm font-semibold text-gray-400 mb-3 uppercase tracking-wider">Role Permissions</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className={`inline-flex items-center px-2 py-0.5 text-xs rounded border ${ROLE_COLORS.viewer}`}>Viewer</span>
            <p className="text-gray-500 mt-1">Read-only access to all data and reports</p>
          </div>
          <div>
            <span className={`inline-flex items-center px-2 py-0.5 text-xs rounded border ${ROLE_COLORS.analyst}`}>Analyst</span>
            <p className="text-gray-500 mt-1">Viewer + run scans, generate reports, export data</p>
          </div>
          <div>
            <span className={`inline-flex items-center px-2 py-0.5 text-xs rounded border ${ROLE_COLORS.investigator}`}>Investigator</span>
            <p className="text-gray-500 mt-1">Analyst + modify review queue, assign cases, add notes</p>
          </div>
          <div>
            <span className={`inline-flex items-center px-2 py-0.5 text-xs rounded border ${ROLE_COLORS.admin}`}>Admin</span>
            <p className="text-gray-500 mt-1">Full access including user management and data deletion</p>
          </div>
        </div>
      </div>
    </div>
  )
}
