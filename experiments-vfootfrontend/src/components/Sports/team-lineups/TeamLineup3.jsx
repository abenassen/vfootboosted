const lineup = [
  {
    id: 1,
    players: [
      {
        id: 1,
        number: '01',
        position: 'GK',
        name: 'N. Rodgers',
        img: 'https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-7.png',
        actions: [
          {
            type: 'yellow-card',
          },
        ],
      },
      {
        id: 2,
        number: '16',
        position: 'DF',
        name: 'A.M. Stevens ',
        img: 'https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-10.png',
        actions: [
          {
            type: 'goal-penalty',
          },
        ],
      },
      {
        id: 3,
        number: '05',
        position: 'MF',
        name: 'P. Stark',
        img: 'https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-11.png',
      },
      {
        id: 4,
        number: '09',
        position: 'FD',
        name: 'J. Sporty ',
        img: 'https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-1.png',
        actions: [
          {
            type: 'goal',
          },
          {
            type: 'sub-out',
          },
        ],
      },
      {
        id: 5,
        number: '37',
        position: 'FD',
        name: 'L. LeBeau',
        img: 'https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-3.png',
      },
    ],
  },
  {
    id: 2,
    title: 'Substitutes',
    players: [
      {
        id: 1,
        number: '03',
        position: 'DF',
        name: 'M. Jameson',
      },
      {
        id: 2,
        number: '07',
        position: 'MF',
        name: 'C. McCoy',
        img: 'https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-12.png',
      },
      {
        id: 3,
        number: '03',
        position: 'FD',
        name: 'C. West',
        img: 'https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-13.png',
        actions: [
          {
            type: 'sub-in',
          },
        ],
      },
    ],
  },
];

function LineupIcon({ type }) {
  return (
    <div className="inline-flex aspect-square w-5 items-center justify-center">
      {type === 'yellow-card' && (
        <svg width="10" height="12" viewBox="0 0 10 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect width="10" height="12" rx="2" fill="#FFC700" />
        </svg>
      )}
      {type === 'red-card' && (
        <svg width="10" height="12" viewBox="0 0 10 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect width="10" height="12" rx="2" fill="#FF2C4F" />
        </svg>
      )}
      {type === 'goal-penalty' && (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="6" cy="6" r="6" fill="#252831" />
          <circle cx="6" cy="6" r="5" fill="white" />
          <path d="M6 4L7.90211 5.38197L7.17557 7.61803H4.82443L4.09789 5.38197L6 4Z" fill="#252831" />
          <path d="M4.21114 1H3.5L6.00002 3L8.5 1H7.78886H4.21114Z" fill="#252831" />
          <path d="M0.10557 5.28124L0.535233 5.77311L2.73206 4.73203L2.53523 2.30901L1.89443 2.18285L0.10557 5.28124Z" fill="#252831" />
          <path d="M11.8631 5.28124L11.4334 5.77311L9.23657 4.73203L9.43339 2.30901L10.0742 2.18285L11.8631 5.28124Z" fill="#252831" />
          <path d="M0.908872 8.62416L1.21144 8.04537L3.59095 8.54321L3.96685 10.945L3.37339 11.2176L0.908872 8.62416Z" fill="#252831" />
          <path d="M11.0598 8.62416L10.7572 8.04537L8.37768 8.54321L8.00178 10.945L8.59523 11.2176L11.0598 8.62416Z" fill="#252831" />
          <path fillRule="evenodd" clipRule="evenodd" d="M6 12C9.31371 12 12 9.31371 12 6C12 2.68629 9.31371 0 6 0V12Z" fill="#252831" />
          <path
            d="M7.33025 9V4.63637H9.13281C9.45951 4.63637 9.74148 4.70029 9.97869 4.82813C10.2173 4.95455 10.4013 5.1314 10.5305 5.35867C10.6598 5.58452 10.7244 5.84731 10.7244 6.14702C10.7244 6.44816 10.6584 6.71165 10.5263 6.9375C10.3956 7.16194 10.2088 7.33594 9.96591 7.45952C9.72301 7.5831 9.43466 7.64489 9.10085 7.64489H7.98863V6.81392H8.90483C9.06392 6.81392 9.19673 6.78623 9.30326 6.73083C9.41122 6.67543 9.4929 6.59802 9.54829 6.49858C9.60369 6.39773 9.63139 6.28054 9.63139 6.14702C9.63139 6.01208 9.60369 5.8956 9.54829 5.79759C9.4929 5.69816 9.41122 5.62145 9.30326 5.56748C9.19531 5.5135 9.0625 5.48651 8.90483 5.48651H8.38494V9H7.33025Z"
            fill="white"
          />
        </svg>
      )}
      {type === 'goal' && (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="6" cy="6" r="6" fill="#252831" />
          <circle cx="6" cy="6" r="5" fill="white" />
          <path d="M6 4L7.90211 5.38197L7.17557 7.61803H4.82443L4.09789 5.38197L6 4Z" fill="#252831" />
          <path d="M4.21114 1H3.5L6.00002 3L8.5 1H7.78886H4.21114Z" fill="#252831" />
          <path d="M0.10557 5.28124L0.535233 5.77311L2.73206 4.73203L2.53523 2.30901L1.89443 2.18285L0.10557 5.28124Z" fill="#252831" />
          <path d="M11.8631 5.28124L11.4334 5.77311L9.23657 4.73203L9.43339 2.30901L10.0742 2.18285L11.8631 5.28124Z" fill="#252831" />
          <path d="M0.908872 8.62416L1.21144 8.04537L3.59095 8.54321L3.96685 10.945L3.37339 11.2176L0.908872 8.62416Z" fill="#252831" />
          <path d="M11.0598 8.62416L10.7572 8.04537L8.37768 8.54321L8.00178 10.945L8.59523 11.2176L11.0598 8.62416Z" fill="#252831" />
        </svg>
      )}
      {type === 'sub-out' && (
        <svg width="8" height="12" viewBox="0 0 8 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M5.81822 0L8.00004 2.25L4.36368 5.99999L8.00006 9.75L5.81824 12L3.05176e-05 6L5.81822 0Z" fill="#FF2C4F" />
        </svg>
      )}
      {type === 'sub-in' && (
        <svg width="8" height="12" viewBox="0 0 8 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M2.18185 0L2.71442e-05 2.25L3.63638 5.99999L0 9.75L2.18182 12L8.00003 6L2.18185 0Z" fill="#00D4CF" />
        </svg>
      )}
    </div>
  );
}

export default function TeamLineup3() {
  return (
    <div className="mx-auto w-full sm:w-[340px]">
      <div className="rounded-3xl border border-custom-gray-200 bg-white px-8 py-7 dark:border-custom-gray-600 dark:bg-custom-gray-800">
        <div className="relative -mx-8 -mt-7 px-8 py-7">
          <h3 className="pe-10 text-base/tight font-bold text-custom-gray-900 dark:text-white">Team Lineup V3</h3>
          <div className="absolute end-0 top-0 flex h-14 w-14 items-center justify-center rounded-se-3xl rounded-es-3xl border-s border-b border-custom-gray-200 bg-white dark:border-custom-gray-600 dark:bg-custom-gray-800">
            <svg viewBox="0 0 420 420" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-7 w-7 text-team-golden-primary">
              <path
                d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                fill="currentColor"
              />
              <path
                d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                className="fill-custom-gray-900"
              />
              <path
                d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                className="fill-white"
              />
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                fill="currentColor"
              />
              <path
                d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                className="fill-white"
              />
            </svg>
          </div>
        </div>

        <div className="-mx-8 -mb-7 overflow-x-auto rounded-3xl bg-white ring-1 ring-custom-gray-200 dark:bg-custom-gray-800 dark:ring-custom-gray-600">
          <div className="grid grid-cols-[auto_auto_1fr_auto] gap-x-3.5">
            {/* Heading */}
            <div className="col-span-full -mb-6 grid grid-cols-subgrid bg-custom-gray-100 pb-6 text-xs/tight font-bold text-custom-gray-900 uppercase dark:bg-custom-gray-700 dark:text-white">
              <div className="py-4 ps-8">#</div>
              <div className="py-4">P</div>
              <div className="py-4">Player</div>
              <div className="py-4 pe-8 text-end"></div>
            </div>
            {/* Heading / End */}

            {/* Groups */}
            {lineup.map((group, groupIndex) => (
              <div key={group.id} className="col-span-full grid grid-cols-subgrid">
                {group.title && (
                  <div
                    className={`col-span-full -mb-6 rounded-t-3xl px-8 pt-4 pb-10 text-xs/tight font-bold text-white uppercase ring-1 ring-custom-gray-200 dark:ring-custom-gray-600 [&+div]:rounded-t-3xl [&+div]:ring-1 [&+div]:ring-custom-gray-200 dark:[&+div]:ring-custom-gray-600 ${
                      groupIndex === 1 ? 'bg-custom-blue' : 'bg-custom-gray-900 dark:bg-white dark:text-custom-gray-900'
                    }`}
                  >
                    {group.title}
                  </div>
                )}

                {/* Players */}
                {group.players.map((player) => (
                  <div
                    key={player.id}
                    className="col-span-full grid grid-cols-subgrid items-center border-b border-custom-gray-200 bg-white text-xs/tight first:rounded-t-3xl first:ring-1 first:ring-custom-gray-200 last:border-b-0 dark:border-custom-gray-600 dark:bg-custom-gray-800 dark:first:ring-custom-gray-600"
                  >
                    <div className="py-4 ps-8 text-custom-gray dark:text-custom-gray-400">{player.number}</div>
                    <div className="py-4 font-bold">{player.position}</div>
                    <div className="py-4 font-bold">{player.name}</div>
                    <div className="flex justify-end gap-0.5 py-3 pe-8 text-end">
                      {player.actions && player.actions.map((action) => <LineupIcon key={action.type} type={action.type} />)}
                    </div>
                  </div>
                ))}
                {/* Players / End */}
              </div>
            ))}
            {/* Groups / End */}
          </div>
        </div>
      </div>
    </div>
  );
}
