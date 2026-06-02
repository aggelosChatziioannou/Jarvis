import type { GraphNode, GraphConnection, Reminder, EpisodicMemory, MemoryHistory } from '@/console/types';

export const sampleNodes: GraphNode[] = [
  { id: 'center', label: 'YOU', category: 'Identity', importance: 1, confidence: 1, permanent: true, emphasis: 1, recentlyChanged: false },
  // Identity cluster
  { id: 'name', label: 'Name', category: 'Identity', importance: 0.9, confidence: 1, permanent: true, emphasis: 0.8, recentlyChanged: false, value: 'Alex' },
  { id: 'age', label: 'Age', category: 'Identity', importance: 0.6, confidence: 0.9, permanent: true, emphasis: 0.3, recentlyChanged: false, value: '28' },
  { id: 'location', label: 'Location', category: 'Identity', importance: 0.8, confidence: 0.95, permanent: false, ttl: 180, emphasis: 0.6, recentlyChanged: true, value: 'Ioannina' },
  { id: 'occupation', label: 'Occupation', category: 'Identity', importance: 0.7, confidence: 0.9, permanent: true, emphasis: 0.5, recentlyChanged: false, value: 'Software Engineer' },
  { id: 'language', label: 'Language', category: 'Identity', importance: 0.8, confidence: 1, permanent: true, emphasis: 0.7, recentlyChanged: false, value: 'English, Greek' },
  { id: 'timezone', label: 'Timezone', category: 'Identity', importance: 0.5, confidence: 0.95, permanent: false, ttl: 90, emphasis: 0.4, recentlyChanged: false, value: 'EET (UTC+2)' },
  // Preferences cluster
  { id: 'theme', label: 'UI Theme', category: 'Preferences', importance: 0.6, confidence: 1, permanent: true, emphasis: 0.4, recentlyChanged: false, value: 'Dark' },
  { id: 'voice-speed', label: 'Voice Speed', category: 'Preferences', importance: 0.5, confidence: 0.85, permanent: true, emphasis: 0.3, recentlyChanged: false, value: '1.0x' },
  { id: 'tts-engine', label: 'TTS Engine', category: 'Preferences', importance: 0.7, confidence: 0.9, permanent: true, emphasis: 0.5, recentlyChanged: true, value: 'Piper' },
  { id: 'wake-word', label: 'Wake Word', category: 'Preferences', importance: 0.8, confidence: 0.95, permanent: true, emphasis: 0.6, recentlyChanged: false, value: '"Hey Jarvis"' },
  { id: 'notifications', label: 'Notifications', category: 'Preferences', importance: 0.4, confidence: 0.7, permanent: false, ttl: 30, emphasis: 0.2, recentlyChanged: false, value: 'Enabled' },
  { id: 'music-genre', label: 'Music Genre', category: 'Preferences', importance: 0.3, confidence: 0.8, permanent: true, emphasis: 0.2, recentlyChanged: false, value: 'Electronic, Ambient' },
  { id: 'coffee', label: 'Coffee', category: 'Preferences', importance: 0.4, confidence: 0.9, permanent: true, emphasis: 0.3, recentlyChanged: false, value: 'Black, no sugar' },
  // Events cluster
  { id: 'dentist', label: 'Dentist Appt', category: 'Events', importance: 0.7, confidence: 0.9, permanent: false, ttl: 7, emphasis: 0.5, recentlyChanged: true, value: '2026-05-30 17:00' },
  { id: 'birthday', label: 'Birthday', category: 'Events', importance: 0.9, confidence: 1, permanent: true, emphasis: 0.7, recentlyChanged: false, value: '1998-03-15' },
  { id: 'meeting', label: 'Team Standup', category: 'Events', importance: 0.6, confidence: 0.8, permanent: false, ttl: 1, emphasis: 0.4, recentlyChanged: false, value: 'Daily 09:00' },
  { id: 'conference', label: 'DevCon 2026', category: 'Events', importance: 0.8, confidence: 0.7, permanent: false, ttl: 120, emphasis: 0.6, recentlyChanged: false, value: '2026-09-15' },
  { id: 'vacation', label: 'Vacation', category: 'Events', importance: 0.7, confidence: 0.6, permanent: false, ttl: 90, emphasis: 0.5, recentlyChanged: false, value: '2026-08-01' },
  // Directives cluster
  { id: 'greeting', label: 'Greeting Style', category: 'Directives', importance: 0.5, confidence: 0.9, permanent: true, emphasis: 0.3, recentlyChanged: false, value: 'Casual, friendly' },
  { id: 'privacy', label: 'Privacy Level', category: 'Directives', importance: 0.9, confidence: 1, permanent: true, emphasis: 0.8, recentlyChanged: false, value: 'High - local only' },
  { id: 'automation', label: 'Auto-Tasks', category: 'Directives', importance: 0.7, confidence: 0.85, permanent: true, emphasis: 0.5, recentlyChanged: true, value: 'Weather, Calendar' },
  { id: 'personality', label: 'Personality', category: 'Directives', importance: 0.6, confidence: 0.9, permanent: true, emphasis: 0.4, recentlyChanged: false, value: 'Helpful, witty' },
  { id: 'data-retention', label: 'Data Retention', category: 'Directives', importance: 0.8, confidence: 0.95, permanent: true, emphasis: 0.6, recentlyChanged: false, value: '90 days default' },
  // Health cluster
  { id: 'sleep-schedule', label: 'Sleep', category: 'Health', importance: 0.6, confidence: 0.7, permanent: false, ttl: 30, emphasis: 0.4, recentlyChanged: false, value: '23:00 - 07:00' },
  { id: 'allergies', label: 'Allergies', category: 'Health', importance: 0.9, confidence: 0.95, permanent: true, emphasis: 0.7, recentlyChanged: false, value: 'Penicillin' },
  { id: 'exercise', label: 'Exercise', category: 'Health', importance: 0.5, confidence: 0.6, permanent: false, ttl: 14, emphasis: 0.3, recentlyChanged: false, value: '3x per week' },
  { id: 'diet', label: 'Diet', category: 'Health', importance: 0.4, confidence: 0.8, permanent: true, emphasis: 0.2, recentlyChanged: false, value: 'Omnivore' },
  { id: 'glasses', label: 'Vision', category: 'Health', importance: 0.5, confidence: 0.9, permanent: true, emphasis: 0.3, recentlyChanged: false, value: 'Contacts -2.5' },
];

export const sampleConnections: GraphConnection[] = [
  { source: 'center', target: 'name', strength: 1 },
  { source: 'center', target: 'age', strength: 0.7 },
  { source: 'center', target: 'location', strength: 0.8 },
  { source: 'center', target: 'occupation', strength: 0.75 },
  { source: 'center', target: 'language', strength: 0.85 },
  { source: 'center', target: 'timezone', strength: 0.6 },
  { source: 'name', target: 'location', strength: 0.3 },
  { source: 'age', target: 'occupation', strength: 0.4 },
  { source: 'location', target: 'timezone', strength: 0.9 },
  { source: 'center', target: 'theme', strength: 0.6 },
  { source: 'center', target: 'voice-speed', strength: 0.55 },
  { source: 'center', target: 'tts-engine', strength: 0.7 },
  { source: 'center', target: 'wake-word', strength: 0.75 },
  { source: 'center', target: 'notifications', strength: 0.5 },
  { source: 'center', target: 'music-genre', strength: 0.4 },
  { source: 'center', target: 'coffee', strength: 0.45 },
  { source: 'tts-engine', target: 'voice-speed', strength: 0.8 },
  { source: 'theme', target: 'notifications', strength: 0.3 },
  { source: 'center', target: 'dentist', strength: 0.7 },
  { source: 'center', target: 'birthday', strength: 0.85 },
  { source: 'center', target: 'meeting', strength: 0.65 },
  { source: 'center', target: 'conference', strength: 0.75 },
  { source: 'center', target: 'vacation', strength: 0.7 },
  { source: 'meeting', target: 'occupation', strength: 0.5 },
  { source: 'vacation', target: 'location', strength: 0.4 },
  { source: 'center', target: 'greeting', strength: 0.55 },
  { source: 'center', target: 'privacy', strength: 0.9 },
  { source: 'center', target: 'automation', strength: 0.7 },
  { source: 'center', target: 'personality', strength: 0.65 },
  { source: 'center', target: 'data-retention', strength: 0.8 },
  { source: 'privacy', target: 'data-retention', strength: 0.85 },
  { source: 'automation', target: 'notifications', strength: 0.6 },
  { source: 'center', target: 'sleep-schedule', strength: 0.6 },
  { source: 'center', target: 'allergies', strength: 0.9 },
  { source: 'center', target: 'exercise', strength: 0.55 },
  { source: 'center', target: 'diet', strength: 0.45 },
  { source: 'center', target: 'glasses', strength: 0.5 },
  { source: 'sleep-schedule', target: 'exercise', strength: 0.4 },
  { source: 'diet', target: 'allergies', strength: 0.6 },
];

export const sampleReminders: Reminder[] = [
  { id: 'r1', title: 'Dentist Appointment', time: '17:00', date: '2026-05-30', status: 'pending', category: 'Health' },
  { id: 'r2', title: 'Team Standup', time: '09:00', date: '2026-05-30', status: 'pending', recurring: true, category: 'Events' },
  { id: 'r3', title: 'Buy groceries', time: '18:30', date: '2026-05-30', status: 'pending', category: 'Preferences' },
  { id: 'r4', title: 'Call Mom', time: '20:00', date: '2026-05-29', status: 'completed', category: 'Identity' },
  { id: 'r5', title: 'Review PR #142', time: '14:00', date: '2026-05-29', status: 'snoozed', category: 'Events' },
  { id: 'r6', title: 'Water plants', time: '08:00', date: '2026-05-31', status: 'pending', recurring: true, category: 'Preferences' },
  { id: 'r7', title: 'Dentist follow-up', time: '10:00', date: '2026-06-06', status: 'pending', category: 'Health' },
  { id: 'r8', title: 'Weekly review', time: '16:00', date: '2026-05-30', status: 'pending', category: 'Directives' },
];

export const sampleEpisodic: EpisodicMemory[] = [
  { id: 'e1', date: '2026-05-28', content: 'User was sick, no work done' },
  { id: 'e2', date: '2026-05-27', content: 'User visited the new cafe on Main St, seemed to enjoy it' },
  { id: 'e3', date: '2026-05-25', content: 'Late night coding session until 3 AM' },
  { id: 'e4', date: '2026-05-22', content: 'User mentioned preferring tea over coffee lately' },
  { id: 'e5', date: '2026-05-20', content: 'Completed the refactoring of auth module' },
  { id: 'e6', date: '2026-05-18', content: 'User went for a 5km run, mentioned knee felt good' },
];

export const sampleHistory: MemoryHistory[] = [
  {
    nodeId: 'location',
    versions: [
      { value: 'Thessaloniki', timestamp: '2026-01-15', reason: 'Initial setting' },
      { value: 'Athens', timestamp: '2026-03-20', reason: 'Temporary move' },
      { value: 'Ioannina', timestamp: '2026-05-29', reason: 'Permanent relocation' },
    ],
  },
  {
    nodeId: 'tts-engine',
    versions: [
      { value: 'Chatterbox', timestamp: '2026-04-01', reason: 'Testing GPU TTS' },
      { value: 'Piper', timestamp: '2026-05-28', reason: 'Better for local use' },
    ],
  },
  {
    nodeId: 'automation',
    versions: [
      { value: 'None', timestamp: '2026-01-01', reason: 'Default' },
      { value: 'Weather only', timestamp: '2026-03-15', reason: 'Added weather check' },
      { value: 'Weather, Calendar', timestamp: '2026-05-25', reason: 'Added calendar sync' },
    ],
  },
];
