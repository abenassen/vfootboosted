//import TeamTactic1 from "@components/Sports/team-tactics/TeamTactic1.jsx";

import {SoccerField} from "@components/Sports/team-tactics/TeamTactic1.jsx";

export default function Home() {
    const zones = [
        { top: '0%', left: '0%', width: '33%', height: '33%', color: 'blue' },
        { top: '0%', left: '33%', width: '33%', height: '33%', color: 'blue' },
        { top: '0%', left: '66%', width: '33%', height: '33%', color: 'blue' },
        { top: '33%', left: '0%', width: '50%', height: '33%', color: 'blue' },
        { top: '33%', left: '50%', width: '50%', height: '33%', color: 'blue' },
        { top: '66%', left: '0%', width: '33%', height: '33%', color: 'blue' },
        { top: '66%', left: '33%', width: '33%', height: '33%', color: 'blue' },
        { top: '66%', left: '66%', width: '33%', height: '33%', color: 'blue' }];

    return (
        <div className="relative mx-auto w-full sm:w-[460px]">
            <SoccerField className="-z-10 w-full h-full" />
            {zones.map((zone, index) => (
                <div
                    key={index}
                    className="absolute transition-all duration-300"
                    style={{
                        top: zone.top,
                        left: zone.left,
                        width: zone.width,
                        height: zone.height,
                        backgroundColor: zone.color,
                        opacity: 0,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.opacity = 0.2)}
                    onMouseLeave={(e) => (e.currentTarget.style.opacity = 0)}
                ></div>
            ))}
        </div>
        );
    }