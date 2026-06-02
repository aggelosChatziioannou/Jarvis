import Card from '@/console/components/Card'
import { AudioEngineProvider } from '@/console/context/AudioEngineContext'
import WaveformBand from '@/console/zones/audio/WaveformBand'
import SpectrumRibbon from '@/console/zones/audio/SpectrumRibbon'
import AudioOrb from '@/console/zones/audio/AudioOrb'
import HealthStrip from '@/console/zones/audio/HealthStrip'
import DeviceControls from '@/console/zones/audio/DeviceControls'
import SensitivitySliders from '@/console/zones/audio/SensitivitySliders'
import AudioEventsFeed from '@/console/zones/audio/AudioEventsFeed'

export default function AudioPage() {
  return (
    <AudioEngineProvider>
      <div className="flex gap-4 h-full">
        {/* Left hero (60%) */}
        <div className="flex-[60] min-w-0 flex flex-col gap-3">
          <Card className="flex-shrink-0 h-[88px]" noPadding>
            <WaveformBand />
          </Card>

          <div className="flex-1 min-h-0 flex gap-3">
            <div className="flex-[3] min-w-0">
              <Card className="h-full" noPadding><AudioOrb /></Card>
            </div>
            <div className="flex-1 min-w-0">
              <Card className="h-full" noPadding><SpectrumRibbon /></Card>
            </div>
          </div>

          <div className="flex-shrink-0">
            <HealthStrip />
          </div>
        </div>

        {/* Right column (40%) */}
        <div className="flex-[40] min-w-0 flex flex-col gap-3">
          <div className="flex-shrink-0"><DeviceControls /></div>
          <div className="flex-shrink-0"><SensitivitySliders /></div>
          <div className="flex-1 min-h-0">
            <Card className="h-full" noPadding>
              <div className="p-4 h-full"><AudioEventsFeed /></div>
            </Card>
          </div>
        </div>
      </div>
    </AudioEngineProvider>
  )
}
