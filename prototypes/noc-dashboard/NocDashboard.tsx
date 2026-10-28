import React, { useState } from 'react';
import {
  AlertTriangle,
  AlertOctagon,
  CheckCircle2,
  ChevronRight,
  Database,
  Filter,
  Layers,
  MapPin,
  RefreshCw,
  Search,
  Server,
  TrendingUp,
  Users,
  Zap,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Radio
} from 'lucide-react';

// --- Types ---
interface ActionItem {
  id: string;
  severity: 'critical' | 'attention' | 'warning' | 'info';
  title: string;
  description: string;
  nodeId?: string;
  actionLabel: string;
  timestamp: string;
}

interface AreaStat {
  name: string;
  customers: number;
  utilization: number;
  pccCount: number;
  legacyCount: number;
  availablePorts: number;
  status: 'nominal' | 'warning' | 'critical';
}

interface PCCNode {
  id: string;
  area: string;
  capacity: number;
  used: number;
  migrationRate: number;
  x: number; // SVG map coordinate percentage
  y: number;
  status: 'critical' | 'warning' | 'normal';
}

// --- Mock Data ---
const INITIAL_ACTION_ITEMS: ActionItem[] = [
  {
    id: 'act-1',
    severity: 'critical',
    title: 'Capacity Exhausted',
    description: 'PCC-0042 in Lekki Central has reached 100% occupancy (16/16 ports allocated).',
    nodeId: 'PCC-0042',
    actionLabel: 'Re-route / Expand',
    timestamp: '2 mins ago'
  },
  {
    id: 'act-2',
    severity: 'attention',
    title: 'Low Asset Utilization',
    description: 'Ajah sector utilization is at 31.0%. 916 drop ports remaining idle.',
    nodeId: 'AJAH-SEC',
    actionLabel: 'View Marketing Recs',
    timestamp: '14 mins ago'
  },
  {
    id: 'act-3',
    severity: 'warning',
    title: 'Civil Deployment Delay',
    description: 'Lekki Phase 3 optical trunk construction is 4 days behind schedule.',
    nodeId: 'PRJ-L3',
    actionLabel: 'View Project Track',
    timestamp: '1 hour ago'
  }
];

const AREA_STATS: AreaStat[] = [
  {
    name: 'Lekki Central',
    customers: 3842,
    utilization: 87.5,
    pccCount: 126,
    legacyCount: 58,
    availablePorts: 182,
    status: 'warning'
  },
  {
    name: 'Ajah Sector',
    customers: 2104,
    utilization: 31.0,
    pccCount: 94,
    legacyCount: 112,
    availablePorts: 916,
    status: 'critical'
  },
  {
    name: 'Victoria Island',
    customers: 4521,
    utilization: 74.2,
    pccCount: 210,
    legacyCount: 14,
    availablePorts: 640,
    status: 'nominal'
  },
  {
    name: 'Ikeja Industrial',
    customers: 2378,
    utilization: 68.4,
    pccCount: 88,
    legacyCount: 42,
    availablePorts: 320,
    status: 'nominal'
  }
];

const MAP_NODES: PCCNode[] = [
  { id: 'PCC-0042', area: 'Lekki Central', capacity: 16, used: 16, migrationRate: 92.0, x: 62, y: 48, status: 'critical' },
  { id: 'PCC-0098', area: 'Ajah Sector', capacity: 16, used: 5, migrationRate: 24.5, x: 78, y: 65, status: 'warning' },
  { id: 'PCC-0104', area: 'Victoria Island', capacity: 32, used: 22, migrationRate: 88.1, x: 35, y: 52, status: 'normal' },
  { id: 'PCC-0012', area: 'Ikeja Industrial', capacity: 16, used: 11, migrationRate: 64.0, x: 28, y: 25, status: 'normal' },
  { id: 'PCC-0071', area: 'Lekki Phase 2', capacity: 16, used: 14, migrationRate: 78.3, x: 52, y: 38, status: 'warning' }
];

export default function NocDashboard() {
  const [selectedNode, setSelectedNode] = useState<PCCNode | null>(MAP_NODES[0]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const handleRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => setIsRefreshing(false), 800);
  };

  return (
    <div className="flex flex-col min-h-screen bg-[#0B0F17] text-slate-100 font-sans antialiased selection:bg-cyan-500/30">
      
      {/* --- TOP APPLICATION BAR --- */}
      <header className="h-16 border-b border-slate-800 bg-[#0B0F17]/90 backdrop-blur sticky top-0 z-30 flex items-center justify-between px-6">
        <div className="flex items-center space-x-3">
          <div className="bg-cyan-500/10 p-2 rounded-lg border border-cyan-500/30">
            <Radio className="h-5 w-5 text-cyan-400 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-xs font-semibold tracking-wider text-cyan-400 uppercase">OPSYN</span>
              <span className="text-xs text-slate-500">/</span>
              <span className="text-xs text-slate-400">Overview</span>
              <span className="text-xs text-slate-500">/</span>
              <span className="text-xs text-slate-200 font-medium">Infrastructure Intelligence</span>
            </div>
            <h1 className="text-sm font-bold text-slate-100 tracking-tight">Executive Command Centre</h1>
          </div>
        </div>

        {/* Global Search & Sync Status */}
        <div className="flex items-center space-x-4">
          <div className="relative w-80">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search customers, boxes, FATs, projects..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-900/80 text-xs text-slate-200 placeholder-slate-500 rounded-md border border-slate-800 pl-9 pr-4 py-2 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all"
            />
          </div>

          <div className="h-4 w-px bg-slate-800" />

          <button
            onClick={handleRefresh}
            className="flex items-center space-x-2 bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
          >
            <RefreshCw className={`h-3.5 w-3.5 text-slate-400 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          <div className="flex items-center space-x-2 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1.5 rounded-md">
            <div className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
            <span className="text-[11px] font-mono text-emerald-400">● Data Synchronized</span>
          </div>
        </div>
      </header>

      {/* --- MAIN CONTENT AREA --- */}
      <main className="flex-1 p-6 space-y-6 max-w-[1700px] mx-auto w-full">
        
        {/* --- KPI METRIC CARDS --- */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          
          {/* Card 1: Total Customers */}
          <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-5 hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Total Customers</span>
              <div className="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
                <Users className="h-4 w-4 text-cyan-400" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-2xl font-bold font-mono text-slate-100">12,845</span>
              <span className="inline-flex items-center text-xs font-medium text-emerald-400">
                <ArrowUpRight className="h-3 w-3 mr-0.5" /> +4.8%
              </span>
            </div>
            <p className="mt-1 text-[11px] text-slate-500">vs. previous period baseline</p>
          </div>

          {/* Card 2: Infrastructure Nodes */}
          <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-5 hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Total Infrastructure</span>
              <div className="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
                <Server className="h-4 w-4 text-indigo-400" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-2xl font-bold font-mono text-slate-100">1,426</span>
              <span className="text-xs font-mono text-slate-400">Nodes</span>
            </div>
            <div className="mt-2 flex items-center space-x-3 text-[11px] text-slate-400 border-t border-slate-800/60 pt-2">
              <span>PCC: <strong className="text-slate-200">892</strong></span>
              <span className="text-slate-600">|</span>
              <span>Legacy: <strong className="text-slate-200">534</strong></span>
            </div>
          </div>

          {/* Card 3: Network Utilization */}
          <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-5 hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Network Utilization</span>
              <div className="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
                <Activity className="h-4 w-4 text-amber-400" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-2xl font-bold font-mono text-slate-100">72.4%</span>
              <span className="text-xs text-amber-400 font-medium">Optimal Band</span>
            </div>
            {/* Custom Meter Bar */}
            <div className="mt-3 w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div className="bg-gradient-to-r from-cyan-500 to-amber-400 h-full rounded-full" style={{ width: '72.4%' }} />
            </div>
          </div>

          {/* Card 4: Migration Progress */}
          <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-5 hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">PCC Migration</span>
              <div className="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
                <Zap className="h-4 w-4 text-emerald-400" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-2xl font-bold font-mono text-slate-100">64.8%</span>
              <span className="text-xs font-mono text-slate-400">1,840 / 2,840</span>
            </div>
            <div className="mt-3 w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div className="bg-emerald-400 h-full rounded-full" style={{ width: '64.8%' }} />
            </div>
          </div>
        </div>

        {/* --- MIDDLE SECTION: GIS HEATMAP + ACTION CENTRE --- */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Spatial Heatmap Card (2 Cols) */}
          <div className="lg:col-span-2 bg-[#111827] border border-slate-800/80 rounded-xl flex flex-col overflow-hidden">
            
            {/* Card Header */}
            <div className="p-4 border-b border-slate-800/80 flex items-center justify-between bg-slate-900/40">
              <div className="flex items-center space-x-2">
                <Layers className="h-4 w-4 text-cyan-400" />
                <h2 className="text-xs font-bold tracking-wider text-slate-200 uppercase">PCC Migration & Topology Heatmap</h2>
              </div>
              <div className="flex items-center space-x-2">
                <span className="text-[11px] text-slate-400">Layer:</span>
                <select className="bg-slate-900 border border-slate-800 text-slate-300 text-xs rounded px-2 py-1 focus:outline-none focus:border-cyan-500">
                  <option>Migration Density</option>
                  <option>Port Capacity</option>
                  <option>Feeder Trunk Lines</option>
                </select>
              </div>
            </div>

            {/* Interactive Vector GIS Container */}
            <div className="relative flex-1 min-h-[380px] bg-[#0A0D14] p-4 flex items-center justify-center overflow-hidden">
              
              {/* Map Grid Pattern Background */}
              <div className="absolute inset-0 bg-[linear-gradient(to_right,#1f293715_1px,transparent_1px),linear-gradient(to_bottom,#1f293715_1px,transparent_1px)] bg-[size:24px_24px]" />

              {/* Simulated GIS Fiber Lines */}
              <svg className="absolute inset-0 w-full h-full pointer-events-none">
                <path d="M 180 180 Q 280 120 420 180 T 620 220" stroke="#0284C7" strokeWidth="2" fill="none" strokeDasharray="4 4" opacity="0.6" />
                <path d="M 420 180 Q 520 280 620 220" stroke="#7E22CE" strokeWidth="1.5" fill="none" opacity="0.5" />
              </svg>

              {/* Spatial Nodes */}
              {MAP_NODES.map((node) => {
                const isSelected = selectedNode?.id === node.id;
                const statusColor = 
                  node.status === 'critical' ? 'bg-red-500 shadow-red-500/50' :
                  node.status === 'warning' ? 'bg-amber-500 shadow-amber-500/50' : 'bg-emerald-500 shadow-emerald-500/50';

                return (
                  <button
                    key={node.id}
                    onClick={() => setSelectedNode(node)}
                    style={{ left: `${node.x}%`, top: `${node.y}%` }}
                    className={`absolute transform -translate-x-1/2 -translate-y-1/2 group focus:outline-none transition-transform ${isSelected ? 'scale-125 z-20' : 'hover:scale-110 z-10'}`}
                  >
                    <div className="relative flex items-center justify-center">
                      <span className={`absolute h-6 w-6 rounded-full ${statusColor} opacity-25 animate-ping`} />
                      <div className={`h-4 w-4 rounded-full border-2 border-slate-900 ${statusColor} shadow-lg`} />
                    </div>
                    
                    {/* Floating Node Label */}
                    <div className="absolute top-5 left-1/2 transform -translate-x-1/2 whitespace-nowrap bg-slate-900/90 backdrop-blur border border-slate-800 text-[10px] font-mono text-slate-300 px-1.5 py-0.5 rounded shadow">
                      {node.id}
                    </div>
                  </button>
                );
              })}

              {/* GIS Overlay Inspector Panel */}
              {selectedNode && (
                <div className="absolute bottom-4 left-4 bg-slate-900/90 backdrop-blur border border-slate-800 rounded-lg p-3 text-xs w-64 shadow-xl z-20">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-2">
                    <span className="font-mono font-bold text-cyan-400">{selectedNode.id}</span>
                    <span className="text-[10px] bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded">{selectedNode.area}</span>
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Port Capacity:</span>
                      <span className="font-mono text-slate-200">{selectedNode.used} / {selectedNode.capacity}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Migration Rate:</span>
                      <span className="font-mono text-emerald-400">{selectedNode.migrationRate}%</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-1 mt-1">
                      <div 
                        className={`h-full rounded-full ${selectedNode.used === selectedNode.capacity ? 'bg-red-500' : 'bg-cyan-400'}`} 
                        style={{ width: `${(selectedNode.used / selectedNode.capacity) * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Map Legend */}
              <div className="absolute top-4 right-4 bg-slate-900/80 backdrop-blur border border-slate-800/80 rounded-md p-2.5 text-[10px] space-y-1.5">
                <div className="font-semibold text-slate-400 uppercase tracking-wider mb-1">Status Legend</div>
                <div className="flex items-center space-x-2">
                  <span className="h-2 w-2 rounded-full bg-red-500" />
                  <span className="text-slate-300">Exhausted (100%)</span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="h-2 w-2 rounded-full bg-amber-500" />
                  <span className="text-slate-300">Warning (&gt;85%)</span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  <span className="text-slate-300">Nominal</span>
                </div>
              </div>
            </div>
          </div>

          {/* Intelligent Action Centre Widget (1 Col) */}
          <div className="bg-[#111827] border border-slate-800/80 rounded-xl flex flex-col">
            
            <div className="p-4 border-b border-slate-800/80 flex items-center justify-between bg-slate-900/40">
              <div className="flex items-center space-x-2">
                <AlertOctagon className="h-4 w-4 text-red-400" />
                <h2 className="text-xs font-bold tracking-wider text-slate-200 uppercase">Action Centre</h2>
              </div>
              <span className="bg-red-500/10 border border-red-500/30 text-red-400 font-mono text-[10px] px-2 py-0.5 rounded-full font-semibold">
                {INITIAL_ACTION_ITEMS.length} Action Items
              </span>
            </div>

            <div className="p-4 space-y-3 flex-1 overflow-y-auto max-h-[380px]">
              {INITIAL_ACTION_ITEMS.map((item) => {
                const borderClass = 
                  item.severity === 'critical' ? 'border-l-red-500 bg-red-500/5' :
                  item.severity === 'attention' ? 'border-l-amber-500 bg-amber-500/5' : 'border-l-indigo-500 bg-indigo-500/5';
                
                return (
                  <div key={item.id} className={`border-l-2 ${borderClass} border-r border-t border-b border-slate-800/80 rounded-r-lg p-3 space-y-2 transition-all hover:border-slate-700`}>
                    <div className="flex items-center justify-between">
                      <span className={`text-[10px] font-bold uppercase tracking-wider ${item.severity === 'critical' ? 'text-red-400' : 'text-amber-400'}`}>
                        {item.severity}
                      </span>
                      <span className="text-[10px] text-slate-500">{item.timestamp}</span>
                    </div>
                    
                    <h3 className="text-xs font-semibold text-slate-200">{item.title}</h3>
                    <p className="text-[11px] text-slate-400 leading-relaxed">{item.description}</p>
                    
                    <div className="pt-1 flex justify-end">
                      <button className="flex items-center space-x-1 text-xs font-medium text-cyan-400 hover:text-cyan-300 transition-colors">
                        <span>{item.actionLabel}</span>
                        <ChevronRight className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* --- BOTTOM SECTION: AREA PERFORMANCE GRID --- */}
        <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xs font-bold tracking-wider text-slate-200 uppercase">Sector Performance & Infrastructure Allocation</h2>
              <p className="text-[11px] text-slate-500">Real-time capacity and spatial density metrics by deployment sector</p>
            </div>
            <button className="text-xs text-cyan-400 hover:text-cyan-300 font-medium flex items-center space-x-1">
              <span>View All Sectors</span>
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {AREA_STATS.map((area) => (
              <div key={area.name} className="bg-slate-900/60 border border-slate-800 rounded-lg p-4 space-y-3 hover:border-slate-700 transition-all">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-slate-100">{area.name}</h3>
                  <span className={`h-2 w-2 rounded-full ${area.status === 'critical' ? 'bg-red-500' : area.status === 'warning' ? 'bg-amber-500' : 'bg-emerald-500'}`} />
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px] pt-1">
                  <div>
                    <span className="text-slate-500 block">Customers</span>
                    <span className="font-mono font-semibold text-slate-200">{area.customers.toLocaleString()}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Available Ports</span>
                    <span className="font-mono font-semibold text-cyan-400">{area.availablePorts}</span>
                  </div>
                </div>

                <div className="space-y-1">
                  <div className="flex justify-between text-[10px]">
                    <span className="text-slate-400">Utilization Rate</span>
                    <span className="font-mono font-semibold text-slate-200">{area.utilization}%</span>
                  </div>
                  <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                    <div 
                      className={`h-full rounded-full ${area.utilization > 85 ? 'bg-amber-500' : area.utilization < 40 ? 'bg-red-500' : 'bg-emerald-400'}`}
                      style={{ width: `${area.utilization}%` }}
                    />
                  </div>
                </div>

                <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] text-slate-500">
                  <span>PCC: <strong className="text-slate-300">{area.pccCount}</strong></span>
                  <span>Legacy: <strong className="text-slate-300">{area.legacyCount}</strong></span>
                  <a href={`#area-${area.name}`} className="text-cyan-400 hover:underline">Details →</a>
                </div>
              </div>
            ))}
          </div>
        </div>

      </main>
    </div>
  );
}